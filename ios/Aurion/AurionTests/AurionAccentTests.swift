//
//  AurionAccentTests.swift
//  AurionTests
//
//  #418: physician accent color. Device-independent coverage for the
//  palette parser + the byte-identical gold-default guard (so the default
//  user's chrome is provably unchanged by this slice).
//

import SwiftUI
import UIKit
import Testing
@testable import Aurion

struct AurionAccentTests {

    @Test func from_parsesEveryCuratedKey() {
        #expect(AurionAccent.from("gold") == .gold)
        #expect(AurionAccent.from("teal") == .teal)
        #expect(AurionAccent.from("indigo") == .indigo)
        #expect(AurionAccent.from("rose") == .rose)
        #expect(AurionAccent.from("slate") == .slate)
    }

    @Test func from_fallsBackToGoldForNilOrUnknown() {
        #expect(AurionAccent.from(nil) == .gold)
        #expect(AurionAccent.from("") == .gold)
        #expect(AurionAccent.from("chartreuse") == .gold)
    }

    @Test func palette_hasExactlyFiveKeys() {
        #expect(AurionAccent.allCases.count == 5)
    }

    /// The gold default MUST resolve to the exact brand values the app has
    /// always shipped (#C9A84C / #E5D082 / #B5953D) so existing users see
    /// no change. Compare resolved RGB to ~1/255 tolerance.
    @Test func goldDefault_isByteIdenticalToBrand() {
        // "gold" is the legacy KEY for the default accent; since the
        // PeriTwin rebrand (2026-07-23) its VALUES are the PeriTwin
        // periwinkle scale anchored to the logo stroke.
        assertRGB(AurionAccent.gold.base, 65, 89, 212)    // #4159D4
        assertRGB(AurionAccent.gold.light, 132, 147, 227) // #8493E3
        assertRGB(AurionAccent.gold.dark, 44, 69, 198)    // #2C45C6
    }

    private func assertRGB(_ color: Color, _ r: Int, _ g: Int, _ b: Int) {
        var rr: CGFloat = 0, gg: CGFloat = 0, bb: CGFloat = 0, aa: CGFloat = 0
        UIColor(color).getRed(&rr, green: &gg, blue: &bb, alpha: &aa)
        #expect(abs(Int((rr * 255).rounded()) - r) <= 1)
        #expect(abs(Int((gg * 255).rounded()) - g) <= 1)
        #expect(abs(Int((bb * 255).rounded()) - b) <= 1)
    }
}
