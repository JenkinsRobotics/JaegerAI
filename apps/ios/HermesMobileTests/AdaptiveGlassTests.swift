import XCTest
@testable import HermesMobile

final class AdaptiveGlassTests: XCTestCase {
    private var suiteName: String!
    private var defaults: UserDefaults!

    override func setUp() {
        super.setUp()
        suiteName = "AdaptiveGlassTests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suiteName)
        defaults.removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suiteName)
        defaults = nil
        suiteName = nil
        super.tearDown()
    }

    func testGlassPreferenceDefaultsToEnabled() {
        XCTAssertTrue(GlassPreference.isEnabled(in: defaults))
    }

    func testGlassPreferenceReadsStoredDisabledValue() {
        defaults.set(false, forKey: GlassPreference.isEnabledKey)

        XCTAssertFalse(GlassPreference.isEnabled(in: defaults))
    }

    func testGlassPreferenceReadsStoredEnabledValue() {
        defaults.set(true, forKey: GlassPreference.isEnabledKey)

        XCTAssertTrue(GlassPreference.isEnabled(in: defaults))
    }

    func testSurfaceResolutionPrefersOpaqueWhenReduceTransparencyIsEnabled() {
        let surface = AdaptiveGlassSurface.resolve(
            liquidGlassAvailable: true,
            isGlassEnabled: true,
            reduceTransparency: true
        )

        XCTAssertEqual(surface, .opaque)
    }

    func testSurfaceResolutionFallsBackToMaterialWhenLiquidGlassIsUnavailable() {
        let surface = AdaptiveGlassSurface.resolve(
            liquidGlassAvailable: false,
            isGlassEnabled: true,
            reduceTransparency: false
        )

        XCTAssertEqual(surface, .material)
    }

    func testSurfaceResolutionFallsBackToMaterialWhenGlassIsDisabled() {
        let surface = AdaptiveGlassSurface.resolve(
            liquidGlassAvailable: true,
            isGlassEnabled: false,
            reduceTransparency: false
        )

        XCTAssertEqual(surface, .material)
    }

    func testSurfaceResolutionUsesLiquidGlassWhenAvailableEnabledAndAllowed() {
        let surface = AdaptiveGlassSurface.resolve(
            liquidGlassAvailable: true,
            isGlassEnabled: true,
            reduceTransparency: false
        )

        XCTAssertEqual(surface, .liquidGlass)
    }

    func testScrollEdgeTreatmentDisablesWhenSoftEdgesAreUnavailable() {
        let treatment = AdaptiveScrollEdgeTreatment.resolve(
            softScrollEdgesAvailable: false,
            reduceTransparency: false
        )

        XCTAssertEqual(treatment, .disabled)
    }

    func testScrollEdgeTreatmentDisablesWhenReduceTransparencyIsEnabled() {
        let treatment = AdaptiveScrollEdgeTreatment.resolve(
            softScrollEdgesAvailable: true,
            reduceTransparency: true
        )

        XCTAssertEqual(treatment, .disabled)
    }

    func testScrollEdgeTreatmentUsesSoftWhenAvailableAndAllowed() {
        let treatment = AdaptiveScrollEdgeTreatment.resolve(
            softScrollEdgesAvailable: true,
            reduceTransparency: false
        )

        XCTAssertEqual(treatment, .soft)
    }
}
