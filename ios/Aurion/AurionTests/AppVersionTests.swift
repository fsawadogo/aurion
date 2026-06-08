//
//  AppVersionTests.swift
//  AurionTests
//
//  #352 — pin the discreet "Version X (build Y)" label that shows on the
//  Profile (Legal section) and Login footers. We exercise the pure
//  `AppVersion.label(short:build:)` formatter so the test is independent of
//  the bundle's actual version (which changes every release), plus assert the
//  bundle reads are non-empty and the `version.label` key resolves in EN + FR.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct AppVersionTests {

    // MARK: - Format (pure)

    @Test func label_formatsVersionAndBuild_inEnglish() {
        Localization.setLanguage("en")
        defer { Localization.setLanguage("en") }
        let label = AppVersion.label(short: "2.3", build: "45")
        // Robust to the exact phrasing — the two bundle values must appear and
        // the "Version" lead-in must survive the format substitution.
        #expect(label.contains("2.3"))
        #expect(label.contains("45"))
        #expect(label.hasPrefix("Version"))
        // The key must actually resolve (a miss would echo "version.label").
        #expect(!label.contains("version.label"))
    }

    @Test func label_formatsVersionAndBuild_inFrench() {
        Localization.setLanguage("fr")
        defer { Localization.setLanguage("en") }
        let label = AppVersion.label(short: "1.0", build: "7")
        #expect(label.contains("1.0"))
        #expect(label.contains("7"))
        #expect(!label.contains("version.label"))
    }

    // MARK: - Bundle reads

    @Test func short_and_build_areNonEmpty() {
        // Reads `CFBundleShortVersionString` / `CFBundleVersion` from the
        // hosting app bundle. The dash fallback would still be non-empty, so
        // this guards against an empty string sneaking through.
        #expect(!AppVersion.short.isEmpty)
        #expect(!AppVersion.build.isEmpty)
    }

    @Test func displayLabel_buildsFromBundleValues() {
        Localization.setLanguage("en")
        defer { Localization.setLanguage("en") }
        let label = AppVersion.displayLabel
        #expect(label.contains(AppVersion.short))
        #expect(label.contains(AppVersion.build))
    }

    // MARK: - Localization parity (EN + FR)

    @Test func versionLabelKey_resolvesInBothLanguages() {
        // EN resolves through the active bundle.
        Localization.setLanguage("en")
        defer { Localization.setLanguage("en") }
        #expect(L("version.label") != "version.label", "EN missing version.label")

        // FR is asserted directly against the fr.lproj bundle so the test
        // doesn't depend on the simulator's preferred-language chain.
        guard let fr = Bundle.main.path(forResource: "fr", ofType: "lproj"),
              let frBundle = Bundle(path: fr) else {
            Issue.record("fr.lproj missing from main bundle")
            return
        }
        #expect(
            frBundle.localizedString(forKey: "version.label", value: "version.label", table: nil)
                != "version.label",
            "FR missing version.label"
        )
    }
}
