"""Typed errors for the video-import pipeline (VID-01…).

Kept PHI-free: messages carry bounded reasons (exit codes, stage labels),
never file contents or patient identifiers.
"""

from __future__ import annotations


class VideoImportError(Exception):
    """Base class for video-import failures.

    Carries a bounded, PHI-free ``reason`` (exit code, stage label, etc.)
    suitable for an audit row / job ``error_message`` — never file contents
    or patient identifiers. Subclasses add only a docstring.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class VideoExtractionError(VideoImportError):
    """ffmpeg failed to extract audio/frames from the uploaded video
    (e.g. ``ffmpeg_exit_1``, ``empty_audio_output``)."""


class MaskingFailedError(VideoImportError):
    """A frame could not be masked server-side — fail closed, drop the frame.

    Reserved for the masking slice (VID-04); defined here so the error
    taxonomy lives in one place.
    """


class RawVideoNotPurgedError(VideoImportError):
    """The raw uploaded video could not be confirmed purged post-extraction.

    A hard failure: a job is not "done" while an unmasked video persists.
    """
