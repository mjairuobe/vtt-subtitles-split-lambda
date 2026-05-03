import base64
import io
import json
import unittest
import zipfile

from function.main import handler, split_vtt_file


def build_multipart_body(boundary: str, file_name: str, file_content: str, t_value: str) -> bytes:
    parts = []
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
            "Content-Type: text/vtt\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_content.encode("utf-8"))
    parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(b'Content-Disposition: form-data; name="t"\r\n\r\n')
    parts.append(t_value.encode("utf-8"))
    parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts)


class VttSplitTests(unittest.TestCase):
    def test_split_vtt_yields_16_files_for_15m05s_with_60s_chunks(self):
        vtt_text = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:00.000 --> 00:00:10.000\n"
            "Start\n\n"
            "2\n"
            "00:15:00.000 --> 00:15:05.000\n"
            "Ende\n"
        )
        chunks = split_vtt_file(vtt_text=vtt_text, chunk_seconds=60)
        self.assertEqual(16, len(chunks))
        self.assertTrue(chunks[0].startswith("WEBVTT"))
        self.assertTrue(chunks[-1].startswith("WEBVTT"))

    def test_handler_returns_zip_with_numbered_vtt_files(self):
        vtt_text = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "A\n\n"
            "00:01:00.000 --> 00:01:02.000\n"
            "B\n"
        )
        boundary = "----WebKitFormBoundaryTest"
        body = build_multipart_body(
            boundary=boundary,
            file_name="untertitel.vtt",
            file_content=vtt_text,
            t_value="60",
        )
        event = {
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "body": base64.b64encode(body).decode("ascii"),
            "isBase64Encoded": True,
        }

        result = handler(event, None)
        self.assertEqual(200, result["statusCode"])
        self.assertTrue(result.get("isBase64Encoded"))
        self.assertEqual("application/zip", result["headers"]["Content-Type"])

        zip_bytes = base64.b64decode(result["body"])
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = sorted(zf.namelist())
            self.assertEqual(["untertitel-1.vtt", "untertitel-2.vtt"], names)
            content_1 = zf.read("untertitel-1.vtt").decode("utf-8")
            content_2 = zf.read("untertitel-2.vtt").decode("utf-8")
            self.assertIn("00:00:00.000 --> 00:00:02.000", content_1)
            self.assertIn("00:00:00.000 --> 00:00:02.000", content_2)

    def test_handler_rejects_missing_t(self):
        boundary = "----WebKitFormBoundaryMissingT"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="x.vtt"\r\n'
            "Content-Type: text/vtt\r\n\r\n"
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nx\n\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        result = handler(
            {
                "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                "body": base64.b64encode(body).decode("ascii"),
                "isBase64Encoded": True,
            },
            None,
        )
        self.assertEqual(400, result["statusCode"])
        payload = json.loads(result["body"])
        self.assertIn("Missing required parameter 't'", payload["error"])


if __name__ == "__main__":
    unittest.main()
