//
//  TourOverlayLayoutTests.swift
//  AurionTests
//
//  #352 — pin the coach-mark tooltip placement so the Skip/Next row is never
//  clipped below the safe area, for ANY spotlight position and ANY Dynamic
//  Type size. We exercise the pure `TourOverlay.clampedCardTop(...)` and
//  `cardNeedsScroll(...)` helpers directly (no live view needed).
//
//  Reference geometry: an iPhone-15-ish 393×852 screen with a 59pt top inset
//  (Dynamic Island) and a 34pt home-indicator bottom inset.
//

import CoreGraphics
import Testing
@testable import Aurion

@MainActor
struct TourOverlayLayoutTests {

    private let containerH: CGFloat = 852
    private let safeTop: CGFloat = 59
    private let safeBottom: CGFloat = 34
    private let margin: CGFloat = 16

    private var topLimit: CGFloat { safeTop + margin }
    private var bottomLimit: CGFloat { containerH - safeBottom - margin }

    // MARK: - The Quick Start regression (#352)

    @Test func lowTopHalfSpotlight_keepsCardFullyOnScreen() {
        // A large, low spotlight whose midY is still in the top half but whose
        // bottom edge sits deep in the screen — the Quick Start grid. With a
        // tall card (AX text), placing "below + 18" would run off the bottom;
        // the clamp must pull the card up so its bottom stays visible.
        let spotlight = CGRect(x: 16, y: 300, width: 361, height: 120) // maxY 420, midY 360 (<426)
        let cardHeight: CGFloat = 360

        let top = TourOverlay.clampedCardTop(
            spotlight: spotlight,
            cardHeight: cardHeight,
            containerHeight: containerH,
            safeTop: safeTop,
            safeBottom: safeBottom,
            margin: margin
        )

        #expect(top >= topLimit)
        // The whole card — including the Skip/Next row at its bottom — fits.
        #expect(top + cardHeight <= bottomLimit + 0.5)
    }

    // MARK: - Standard placements stay in bounds

    @Test func smallTopHalfSpotlight_placesBelowAndFits() {
        let spotlight = CGRect(x: 100, y: 120, width: 80, height: 80) // maxY 200, midY 160
        let cardHeight: CGFloat = 220
        let top = TourOverlay.clampedCardTop(
            spotlight: spotlight, cardHeight: cardHeight,
            containerHeight: containerH, safeTop: safeTop, safeBottom: safeBottom, margin: margin
        )
        // Placed just below the spotlight, and fully within the safe band.
        #expect(top >= spotlight.maxY)
        #expect(top + cardHeight <= bottomLimit + 0.5)
    }

    @Test func bottomHalfSpotlight_placesAboveAndFits() {
        let spotlight = CGRect(x: 16, y: 700, width: 361, height: 84) // midY 742 (> 426)
        let cardHeight: CGFloat = 220
        let top = TourOverlay.clampedCardTop(
            spotlight: spotlight, cardHeight: cardHeight,
            containerHeight: containerH, safeTop: safeTop, safeBottom: safeBottom, margin: margin
        )
        #expect(top >= topLimit)
        #expect(top + cardHeight <= bottomLimit + 0.5)
    }

    @Test func noSpotlight_centersWithinSafeBand() {
        let cardHeight: CGFloat = 240
        let top = TourOverlay.clampedCardTop(
            spotlight: nil, cardHeight: cardHeight,
            containerHeight: containerH, safeTop: safeTop, safeBottom: safeBottom, margin: margin
        )
        #expect(top >= topLimit)
        #expect(top + cardHeight <= bottomLimit + 0.5)
        // Roughly centered in the available band.
        let available = bottomLimit - topLimit
        let expectedCenteredTop = topLimit + (available - cardHeight) / 2
        #expect(abs(top - expectedCenteredTop) <= 1.0)
    }

    @Test func tinyDevice_topNeverAboveSafeTop() {
        // Even when the card is taller than the band, the top edge is pinned to
        // the top safe inset (the scroll path then makes Skip/Next reachable).
        let spotlight = CGRect(x: 16, y: 60, width: 361, height: 60)
        let cardHeight: CGFloat = 900
        let top = TourOverlay.clampedCardTop(
            spotlight: spotlight, cardHeight: cardHeight,
            containerHeight: containerH, safeTop: safeTop, safeBottom: safeBottom, margin: margin
        )
        #expect(top >= topLimit - 0.5)
    }

    // MARK: - Scroll fallback

    @Test func tallCard_needsScroll() {
        #expect(
            TourOverlay.cardNeedsScroll(
                cardHeight: 900, containerHeight: containerH,
                safeTop: safeTop, safeBottom: safeBottom, margin: margin
            )
        )
    }

    @Test func shortCard_doesNotNeedScroll() {
        #expect(
            !TourOverlay.cardNeedsScroll(
                cardHeight: 200, containerHeight: containerH,
                safeTop: safeTop, safeBottom: safeBottom, margin: margin
            )
        )
    }
}
