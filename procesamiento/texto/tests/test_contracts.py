import unittest

from texto.contracts import (
    build_transcript_record,
    normalize_media_type,
    normalize_recorded_at,
    validate_subject_id,
)


class TranscriptContractTests(unittest.TestCase):
    def test_transcript_record_keeps_subject_and_normalizes_timestamp(self) -> None:
        record = build_transcript_record(
            job_id="job-1",
            subject_id="subject-42",
            recorded_at="2026-11-14T09:00:00+01:00",
            transcript="Transcription test",
            language="en",
            duration_seconds=2.5,
            classification={
                "model": "classifier",
                "scores": {
                    "LABEL_0": 0.2,
                    "LABEL_1": 0.8,
                    "LABEL_2": 0.3,
                    "LABEL_3": 0.1,
                },
            },
        )

        self.assertEqual(record["subject_id"], "subject-42")
        self.assertEqual(record["recorded_at"], "2026-11-14T08:00:00Z")
        self.assertEqual(record["source"], "audio_transcription")
        self.assertEqual(record["transcript"], "Transcription test")
        self.assertEqual(record["classification"]["scores"]["LABEL_1"], 0.8)
        self.assertNotIn("raw_audio", record)

    def test_rejects_subject_id_that_could_contain_personal_data(self) -> None:
        with self.assertRaises(ValueError):
            validate_subject_id("person@example.com")

    def test_timestamp_must_include_timezone(self) -> None:
        with self.assertRaises(ValueError):
            normalize_recorded_at("2026-11-14T09:00:00")

    def test_browser_webm_content_type_parameters_are_accepted(self) -> None:
        self.assertEqual(
            normalize_media_type("audio/webm;codecs=opus"),
            "audio/webm",
        )
