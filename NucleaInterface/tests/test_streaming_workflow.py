import json
from pathlib import Path


def test_workflow_requests_ticket_instead_of_buffering_an_audio_file():
    workflow = json.loads((Path(__file__).parents[1] / 'workflows/nuclea-streaming.json').read_text(encoding='utf-8'))
    nodes = {node['name']: node for node in workflow['nodes']}
    tts = nodes['HTTP Request TTS']['parameters']
    assert tts['url'].endswith('/v1/audio/speech/streams')
    assert tts['options']['response']['response']['responseFormat'] == 'json'
    assert nodes['Respond to Webhook']['parameters']['respondWith'] == 'json'
    assert nodes['Respond to Webhook']['parameters']['responseBody'] == '={{ $json }}'
    assert workflow['connections']['AI Agent']['main'][0][0]['node'] == 'HTTP Request TTS'
    assert workflow['connections']['HTTP Request TTS']['main'][0][0]['node'] == 'Respond to Webhook'
    assert nodes['Webhook']['parameters']['responseMode'] == 'responseNode'
