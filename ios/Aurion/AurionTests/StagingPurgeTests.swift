//
//  StagingPurgeTests.swift
//  AurionTests
//
//  #282 — raw audio must not outlive its session. Covers the staging-path
//  contract and the reusable directory sweep that powers both the foreground
//  orphan sweep and the discard-time purge.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct StagingPurgeTests {

    // AC-1 — staging path convention (purger finds WAVs by convention,
    // since a crash loses the in-memory URL).
    @Test func fileURLPath() {
        let url = AudioUploadStaging.fileURL(sessionId: "abc-123")
        #expect(url.lastPathComponent == "abc-123.wav")
        #expect(url.deletingLastPathComponent().lastPathComponent == "AudioUploadStaging")
    }

    // AC-2 — sweep deletes files older than maxAge, keeps fresh ones.
    @Test func sweepDeletesOldKeepsFresh() throws {
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("staging-test-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: dir) }

        let old = dir.appendingPathComponent("old.wav")
        let fresh = dir.appendingPathComponent("fresh.wav")
        try Data("x".utf8).write(to: old)
        try Data("y".utf8).write(to: fresh)
        // Backdate `old` two days.
        try fm.setAttributes([.modificationDate: Date().addingTimeInterval(-2 * 24 * 3600)], ofItemAtPath: old.path)

        let deleted = LocalDataPurger.sweep(directory: dir, maxAge: 24 * 3600, filter: { $0.pathExtension == "wav" })
        #expect(deleted == 1)
        #expect(!fm.fileExists(atPath: old.path))
        #expect(fm.fileExists(atPath: fresh.path))
    }

    // AC-3 — maxAge nil deletes every match regardless of age.
    @Test func sweepNilAgeDeletesAll() throws {
        let fm = FileManager.default
        let dir = fm.temporaryDirectory.appendingPathComponent("staging-test-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: dir) }

        try Data("a".utf8).write(to: dir.appendingPathComponent("one.wav"))
        try Data("b".utf8).write(to: dir.appendingPathComponent("two.wav"))
        // A non-matching file must survive the filter.
        try Data("c".utf8).write(to: dir.appendingPathComponent("keep.txt"))

        let deleted = LocalDataPurger.sweep(directory: dir, maxAge: nil, filter: { $0.pathExtension == "wav" })
        #expect(deleted == 2)
        #expect(fm.fileExists(atPath: dir.appendingPathComponent("keep.txt").path))
    }

    // AC-4 — discard-time purge removes the staged WAV, and is a no-op
    // (false) when there's nothing staged.
    @Test func purgeStagedAudioRemovesFile() throws {
        let fm = FileManager.default
        let sessionId = "purge-test-\(UUID().uuidString)"
        let url = AudioUploadStaging.fileURL(sessionId: sessionId)

        // No file yet → false, no crash.
        #expect(LocalDataPurger.purgeStagedAudio(sessionId: sessionId) == false)

        // Stage a file, then purge it.
        try fm.createDirectory(at: AudioUploadStaging.directory, withIntermediateDirectories: true)
        try Data("wav".utf8).write(to: url)
        defer { try? fm.removeItem(at: url) }

        #expect(LocalDataPurger.purgeStagedAudio(sessionId: sessionId) == true)
        #expect(!fm.fileExists(atPath: url.path))
    }
}
