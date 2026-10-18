//
//  AetherTheme.swift
//  JaegerAI / Theme
//
//  Single-source Swift bridge to the shared design tokens defined in
//  jaeger_ai/assets/design-system/aether-default.json.
//  Provides tokenized colors, geometry, metrics, and typography matching
//  the Aether Studio visual family while preserving Jaeger's native controls.
//

import SwiftUI

public enum AetherTheme {
    // MARK: - Dark Shell Palette (Default)
    public static let bgApp            = Color(red: 14/255,  green: 16/255,  blue: 19/255)  // #0e1013
    public static let bgShell          = Color(red: 23/255,  green: 26/255,  blue: 32/255)  // #171a20
    public static let bgBar            = Color(red: 23/255,  green: 26/255,  blue: 32/255)  // #171a20
    public static let bgPanel          = Color(red: 23/255,  green: 26/255,  blue: 32/255)  // #171a20
    public static let bgRail           = Color(red: 23/255,  green: 26/255,  blue: 32/255)  // #171a20
    public static let bgInset          = Color(red: 30/255,  green: 34/255,  blue: 42/255)  // #1e222a
    public static let bgControl        = Color(red: 15/255,  green: 18/255,  blue: 22/255)  // #0f1216
    public static let bgControlHover   = Color(red: 48/255,  green: 57/255,  blue: 69/255)  // #303945
    public static let bgHover          = Color(red: 41/255,  green: 49/255,  blue: 58/255)  // #29313a
    public static let bgRowHover       = Color(red: 37/255,  green: 44/255,  blue: 53/255)  // #252c35
    public static let bgSelected       = Color(red: 23/255,  green: 75/255,  blue: 114/255) // #174b72
    public static let textOnSelected   = Color(red: 255/255, green: 255/255, blue: 255/255) // #ffffff

    public static let border           = Color(red: 48/255,  green: 54/255,  blue: 64/255)  // #303640
    public static let borderControl    = Color(red: 58/255,  green: 66/255,  blue: 77/255)  // #3a424d
    public static let borderFocus      = Color(red: 76/255,  green: 157/255, blue: 255/255) // #4c9dff

    public static let text             = Color(red: 231/255, green: 237/255, blue: 243/255) // #e7edf3
    public static let textSoft         = Color(red: 203/255, green: 213/255, blue: 223/255) // #cbd5df
    public static let textDim          = Color(red: 139/255, green: 150/255, blue: 165/255) // #8b96a5
    public static let textFaint        = Color(red: 111/255, green: 123/255, blue: 137/255) // #6f7b89

    public static let accent           = Color(red: 76/255,  green: 157/255, blue: 255/255) // #4c9dff
    public static let accentStrong     = Color(red: 18/255,  green: 111/255, blue: 186/255) // #126fba
    public static let selectionEdge    = Color(red: 55/255,  green: 168/255, blue: 244/255) // #37a8f4

    public static let ok               = Color(red: 50/255,  green: 207/255, blue: 132/255) // #32cf84
    public static let warn             = Color(red: 231/255, green: 168/255, blue: 67/255)  // #e7a843
    public static let error            = Color(red: 255/255, green: 90/255,  blue: 98/255)  // #ff5a62

    // MARK: - Geometry & Rhythm
    public static let radiusControl: CGFloat = 7
    public static let radiusButton:  CGFloat = 8
    public static let radiusField:   CGFloat = 6
    public static let radiusRow:     CGFloat = 6

    public static let space1: CGFloat = 3
    public static let space2: CGFloat = 5
    public static let space3: CGFloat = 7
    public static let space4: CGFloat = 9
    public static let space5: CGFloat = 13

    public static let sizeGrid:      CGFloat = 4
    public static let sizeRow:       CGFloat = 36
    public static let sizeIconSlot:  CGFloat = 36
    public static let sizeTopbar:    CGFloat = 56
    public static let sizeStatusbar: CGFloat = 27
    public static let sizeRail:      CGFloat = 42
    public static let sizeSidebar:   CGFloat = 250

    // MARK: - Typography
    public static let fontSizeBody:    CGFloat = 12
    public static let fontSizeLabel:   CGFloat = 10
    public static let fontSizeCaption: CGFloat = 9
    public static let fontSizeMicro:   CGFloat = 8

    public static let fontBody    = Font.system(size: 12)
    public static let fontLabel   = Font.system(size: 10)
    public static let fontCaption = Font.system(size: 9)

    // MARK: - Icon Grammar
    public static let iconStrokeWidth: CGFloat = 1.7
    public static let iconViewBoxSize: CGFloat = 24
}

