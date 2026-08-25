//
//  SlashRoutingTests.swift
//  JaegerAITests
//
//  Pure routing for the windowed slash overlay: /model opens the picker,
//  /model use … is a typed switch, typing / filters the palette.
//

import XCTest
@testable import JaegerAI

final class SlashRoutingTests: XCTestCase {

    func testBareModelAndModelsOpenThePicker() {
        XCTAssertTrue(SlashRouting.isBareModelPicker("/model"))
        XCTAssertTrue(SlashRouting.isBareModelPicker("/models"))
        XCTAssertTrue(SlashRouting.isBareModelPicker("  /model  "))
        XCTAssertTrue(SlashRouting.isBareModelPicker("/MODELS"))
    }

    func testModelWithArgsIsNotThePicker() {
        XCTAssertFalse(SlashRouting.isBareModelPicker("/model list"))
        XCTAssertFalse(SlashRouting.isBareModelPicker("/model use ollama qwen"))
        XCTAssertFalse(SlashRouting.isBareModelPicker("/help"))
        XCTAssertFalse(SlashRouting.isBareModelPicker("model"))
        XCTAssertFalse(SlashRouting.isBareModelPicker(""))
    }

    func testModelUseParsesProviderAndMultiwordModel() {
        let parsed = SlashRouting.modelUseArgs("/model use ollama-cloud deepseek-v4-pro:0813")
        XCTAssertEqual(parsed?.provider, "ollama-cloud")
        XCTAssertEqual(parsed?.model, "deepseek-v4-pro:0813")

        let spaced = SlashRouting.modelUseArgs("/model use local gemma 4 e4b")
        XCTAssertEqual(spaced?.provider, "local")
        XCTAssertEqual(spaced?.model, "gemma 4 e4b")
    }

    func testModelUseRejectsBareAndList() {
        XCTAssertNil(SlashRouting.modelUseArgs("/model"))
        XCTAssertNil(SlashRouting.modelUseArgs("/model list"))
        XCTAssertNil(SlashRouting.modelUseArgs("/model use ollama"))
        XCTAssertNil(SlashRouting.modelUseArgs("/help"))
    }

    func testConfigureProviderMapsInProcessBackendsToLocal() {
        XCTAssertEqual(SlashRouting.configureProvider("mlx"), "local")
        XCTAssertEqual(SlashRouting.configureProvider("llama-cpp"), "local")
        XCTAssertEqual(SlashRouting.configureProvider("lm-studio"), "lmstudio")
        XCTAssertEqual(SlashRouting.configureProvider("ollama-cloud"), "ollama-cloud")
    }

    func testPaletteFiltersByPrefixAndHidesOnceArgsStart() {
        let names = { SlashRouting.matchingPalette($0).map(\.name) }
        XCTAssertTrue(names("/").contains("model"))
        XCTAssertTrue(names("/").contains("goal"))
        XCTAssertTrue(names("/").contains("auto"))
        XCTAssertTrue(names("/").contains("plan"))
        XCTAssertEqual(names("/mo"), ["model", "mode"])
        XCTAssertEqual(names("/model"), ["model"])
        XCTAssertEqual(names("/model "), [])
        XCTAssertEqual(names("hello"), [])
    }

    func testGoalWithJobBecomesAChatTurn() {
        let action = SlashRouting.action(for: "/goal improve Apple Notes structure and quality")
        XCTAssertEqual(
            action,
            .chat(
                prompt: "improve Apple Notes structure and quality",
                display: "/goal improve Apple Notes structure and quality"
            )
        )
    }

    func testBareGoalIsLocalNoticeAndAutoPassesThrough() {
        if case .local(let text) = SlashRouting.action(for: "/goal") {
            XCTAssertTrue(text.contains("/goal"))
        } else {
            XCTFail("bare /goal should be a local usage notice")
        }
        XCTAssertEqual(SlashRouting.action(for: "/auto"), .passThrough)
        XCTAssertEqual(SlashRouting.action(for: "/mode auto"), .passThrough)
        XCTAssertEqual(SlashRouting.action(for: "/mode interactive"), .passThrough)
    }

    func testStopAndSteerRouteToControlOps() {
        XCTAssertEqual(SlashRouting.action(for: "/stop"), .stop)
        XCTAssertEqual(SlashRouting.action(for: "/steer keep merging"), .steer("keep merging"))
        if case .local = SlashRouting.action(for: "/steer") {
            // usage notice
        } else {
            XCTFail("bare /steer should be a usage notice")
        }
    }

    func testPlainTextAndHelpPassThrough() {
        XCTAssertEqual(SlashRouting.action(for: "improve my apple notes"), .passThrough)
        XCTAssertEqual(SlashRouting.action(for: "/help"), .passThrough)
        XCTAssertEqual(SlashRouting.action(for: "/new"), .newChat)
    }
}
