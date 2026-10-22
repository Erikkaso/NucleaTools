"""Manual browser smoke: real HTTP, synthetic TTS, no external n8n/GPU required.

Run from repository root: python -m NucleaInterface.tests.browser_streaming_smoke
Requires Playwright and an installed Chromium; does not install model weights.
"""

import os
import socket
import threading
from pathlib import Path

import numpy as np
import requests
import uvicorn
from flask import Flask, jsonify
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from NucleaInterface import app as interface
from voice_runtime.app import create_app
from voice_runtime.runtime import VoiceRuntime


def main():
    release = threading.Event()

    class Engine:
        def load(self): pass
        def warmup(self): pass
        def unload(self): pass

        def synthesize_pcm(self, text):
            if text == 'Segunda.':
                if not release.wait(15):
                    raise RuntimeError('Browser did not release second phrase')
            samples = np.sin(np.arange(48000) * 2 * np.pi * 220 / 24000) * 4000
            return samples.astype('<i2').tobytes(), 24000

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    runtime_url = f'http://127.0.0.1:{sock.getsockname()[1]}'
    runtime = uvicorn.Server(uvicorn.Config(create_app(VoiceRuntime(Engine())), log_level='error'))
    runtime_thread = threading.Thread(target=runtime.run, kwargs={'sockets': [sock]}, daemon=True)
    runtime_thread.start()

    n8n = Flask('mock-n8n')

    @n8n.post('/webhook')
    def webhook():
        response = requests.post(runtime_url + '/v1/audio/speech/streams',
                                 json={'text': 'Primeira. Segunda.'}, timeout=5)
        response.raise_for_status()
        return jsonify(response.json())

    n8n_server = make_server('127.0.0.1', 0, n8n, threaded=True)
    interface.N8N_WEBHOOK_URL = f'http://127.0.0.1:{n8n_server.server_port}/webhook'
    interface.TTS_BASE_URL = runtime_url
    os.environ['TTS_PREBUFFER_SECONDS'] = '0.1'
    interface_server = make_server('127.0.0.1', 0, interface.app, threaded=True)
    servers = [n8n_server, interface_server]
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)

    output = Path('.pytest_cache/voice-browser')
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            executable = os.getenv('CHROMIUM_EXECUTABLE')
            if not executable:
                local = Path(os.getenv('LOCALAPPDATA', '')) / 'ms-playwright'
                executables = list(local.glob('chromium-*/chrome-win64/chrome.exe'))
                executable = str(sorted(executables)[-1]) if executables else None
            browser = playwright.chromium.launch(
                executable_path=executable,
                args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
            )
            context = browser.new_context(permissions=['microphone'], viewport={'width': 1280, 'height': 800})
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{interface_server.server_port}')
            page.locator('#speakButton').click()
            page.wait_for_function("document.querySelector('#voiceApp').dataset.state === 'listening'")
            page.wait_for_timeout(350)
            page.locator('#speakButton').click()
            page.wait_for_function("document.querySelector('#voiceApp').dataset.state === 'speaking'")
            assert not release.is_set(), 'Playback did not precede completion of generation'
            page.wait_for_timeout(200)
            assert page.evaluate("document.querySelector('#waveform').getContext('2d').getImageData(0,0,960,280).data.some((v,i)=>i%4===3&&v>0)")
            page.screenshot(path=str(output / 'desktop-speaking.png'))
            release.set()
            page.wait_for_function("document.querySelector('#voiceApp').dataset.state === 'idle'", timeout=15000)
            for width, height in ((1280, 800), (390, 844)):
                page.set_viewport_size({'width': width, 'height': height})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#speakButton').is_visible()
                assert not page.locator('textarea, input[type=text]').count()
                page.screenshot(path=str(output / f'{width}-idle.png'))
            assert not errors, errors
            browser.close()
        print('PASS: microphone -> mock n8n -> runtime PCM -> browser playback before second phrase completed; desktop/mobile nonblank and no JS errors.')
    finally:
        release.set()
        for server in servers:
            server.shutdown()
        for thread in threads:
            thread.join(3)
        runtime.should_exit = True
        runtime_thread.join(5)
        sock.close()


if __name__ == '__main__':
    main()
