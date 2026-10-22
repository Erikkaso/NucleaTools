from io import BytesIO
import unittest
from unittest.mock import patch

import requests

from NucleaInterface import app as interface_app


def audio_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = b"ID3fake-mp3"
    response.headers["Content-Type"] = "audio/mpeg"
    return response


class DeviceAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        interface_app.device_response_mailbox.clear()
        self.client = interface_app.app.test_client()

    @patch.object(interface_app.requests, "post")
    def test_upload_queues_one_response_for_browser(self, post) -> None:
        post.return_value = audio_response()

        upload = self.client.post(
            "/api/device-audio",
            data={
                "deviceId": "esp32-laboratorio",
                "audio": (BytesIO(b"RIFFfake-wav"), "command.wav"),
            },
            content_type="multipart/form-data",
        )
        browser_response = self.client.get("/api/device-response")
        consumed_response = self.client.get("/api/device-response")

        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.get_json(), {"status": "ready"})
        self.assertEqual(post.call_args.kwargs["data"], {"sessionId": "esp32-laboratorio"})
        self.assertEqual(browser_response.status_code, 200)
        self.assertEqual(browser_response.content_type, "audio/mpeg")
        self.assertEqual(browser_response.data, b"ID3fake-mp3")
        self.assertEqual(consumed_response.status_code, 204)

    def test_upload_requires_audio(self) -> None:
        response = self.client.post(
            "/api/device-audio",
            data={"deviceId": "esp32-laboratorio"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/device-response").status_code, 204)

    def test_page_polls_for_device_response(self) -> None:
        response = self.client.get("/")

        self.assertIn('/static/voice-ui.mjs', response.text)
        script = self.client.get('/static/voice-ui.mjs')
        self.assertEqual(script.status_code, 200)
        self.assertIn("fetcher('/api/device-response'", script.text)

    @patch.object(interface_app.requests, "post")
    def test_upstream_timeout_keeps_previous_response(self, post) -> None:
        interface_app.device_response_mailbox.put(b"previous-mp3", "audio/mpeg")
        post.side_effect = requests.exceptions.Timeout()
        response = self.client.post(
            "/api/device-audio",
            data={"audio": (BytesIO(b"RIFFwav"), "command.wav")},
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(self.client.get("/api/device-response").data, b"previous-mp3")

    @patch.object(interface_app.requests, "post")
    def test_non_audio_response_is_rejected(self, post) -> None:
        upstream = audio_response()
        upstream.headers["Content-Type"] = "application/json"
        post.return_value = upstream
        response = self.client.post(
            "/api/device-audio",
            data={"audio": (BytesIO(b"RIFFwav"), "command.wav")},
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get("/api/device-response").status_code, 204)

    def test_mailbox_replaces_previous_response_and_disables_cache(self) -> None:
        interface_app.device_response_mailbox.put(b"old", "audio/mpeg")
        interface_app.device_response_mailbox.put(b"new", "audio/mpeg")

        response = self.client.get("/api/device-response")

        self.assertEqual(response.data, b"new")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/api/device-response").status_code, 204)

    @patch.object(interface_app.requests, "post")
    def test_existing_browser_flows_return_audio_directly(self, post) -> None:
        post.return_value = audio_response()
        text_response = self.client.post("/api/chat", json={"message": "Ola"})
        audio_response_result = self.client.post(
            "/api/chat-audio",
            data={"audio": (BytesIO(b"recording"), "recording.webm")},
        )

        for response in (text_response, audio_response_result):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"ID3fake-mp3")
            self.assertEqual(response.content_type, "audio/mpeg")
        self.assertEqual(self.client.get("/api/device-response").status_code, 204)


if __name__ == "__main__":
    unittest.main()
