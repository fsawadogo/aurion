//
//  AudioUploadClassifyTests.swift
//  AurionTests
//
//  HTTP-status → AudioUploadErrorCategory classification, with the #3 fix:
//  a 422 from the transcription endpoint is the empty-transcript guard ("no
//  speech captured"), so it maps to a dedicated, friendly, NON-retryable
//  `.noAudio` category instead of the generic, retried `.server4xx`. This is
//  what turns the "95% / server error" hang into a "no speech — re-record"
//  message that doesn't pointlessly re-upload the same silent bytes.
//

import Foundation
import Testing
@testable import Aurion

struct AudioUploadClassifyTests {

    // A 422 whose body carries the empty-transcript guard reason → no-audio.
    @Test func status422WithEmptyTranscriptReasonMapsToNoAudio() {
        let body = #"{"detail":{"reason":"transcript_empty_or_missing","message":"No audio was transcribed..."}}"#
        #expect(AudioUploadCoordinator.classify(httpStatus: 422, body: body) == .noAudio)
        let shortBody = #"{"detail":{"reason":"transcript_too_short"}}"#
        #expect(AudioUploadCoordinator.classify(httpStatus: 422, body: shortBody) == .noAudio)
    }

    // A 422 WITHOUT the guard reason (e.g. FastAPI request-validation on a
    // malformed multipart) must NOT be mislabeled "no speech" — stays generic.
    @Test func status422ValidationStaysServer4xx() {
        let validation = #"{"detail":[{"loc":["body","audio_file"],"msg":"field required"}]}"#
        #expect(AudioUploadCoordinator.classify(httpStatus: 422, body: validation) == .server4xx)
        // No body at all is treated conservatively as a generic 4xx, not no-audio.
        #expect(AudioUploadCoordinator.classify(httpStatus: 422, body: nil) == .server4xx)
    }

    @Test func otherFourXxStaysServer4xx() {
        #expect(AudioUploadCoordinator.classify(httpStatus: 400) == .server4xx)
        #expect(AudioUploadCoordinator.classify(httpStatus: 401) == .server4xx)
        #expect(AudioUploadCoordinator.classify(httpStatus: 404) == .server4xx)
    }

    @Test func fiveXxStaysServer5xx() {
        #expect(AudioUploadCoordinator.classify(httpStatus: 500) == .server5xx)
        #expect(AudioUploadCoordinator.classify(httpStatus: 503) == .server5xx)
    }

    // Re-uploading the same silent bytes can't help — .noAudio must not retry.
    @Test func noAudioIsNotRetryable() {
        #expect(AudioUploadErrorCategory.noAudio.isRetryable == false)
    }

    // Guard the retry contract that .noAudio relies on staying distinct from.
    @Test func retryabilityContract() {
        #expect(AudioUploadErrorCategory.network.isRetryable == true)
        #expect(AudioUploadErrorCategory.server5xx.isRetryable == true)
        #expect(AudioUploadErrorCategory.server4xx.isRetryable == false)
        #expect(AudioUploadErrorCategory.fileMissing.isRetryable == false)
        #expect(AudioUploadErrorCategory.unknown.isRetryable == false)
    }
}
