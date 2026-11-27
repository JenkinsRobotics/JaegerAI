// ControllerPill.swift — Quick input pill (floating window)
// Inspired by Raycast/Spotlight: ⌥Space opens a floating input, type and Enter sends to Jaeger.
// The pill is a CONTROLLER — it sends to the Gateway and opens the main chat.

import AppKit
import JaegerShellCore

/// Floating quick-input pill. Shows at cursor position when hotkey pressed.
final class ControllerPill: NSWindowController, NSTextFieldDelegate {
    
    private let textField: NSTextField
    private let hintLabel: NSTextField
    private let orbView: VoiceOrbView
    private var onSubmit: ((String) -> Void)?
    private var onVoiceTap: (() -> Void)?
    
    // MARK: - Initialization
    
    init() {
        let window = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 60),
            styleMask: [.nonactivatingPanel, .fullSizeContentView, .borderless],
            backing: .buffered,
            defer: false
        )
        window.level = .floating
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.hidesOnDeactivate = false
        window.isReleasedWhenClosed = false
        
        self.textField = NSTextField()
        self.hintLabel = NSTextField()
        self.orbView = VoiceOrbView()
        
        super.init(window: window)
        
        setupUI()
    }
    
    required init?(coder: NSCoder) {
        fatalError("init(coder:) not implemented")
    }
    
    // MARK: - UI Setup
    
    private func setupUI() {
        guard let window = window, let contentView = window.contentView else { return }
        
        // Container with vibrancy
        let container = NSVisualEffectView()
        container.material = .hudWindow
        container.state = .active
        container.wantsLayer = true
        container.layer?.cornerRadius = 12
        container.translatesAutoresizingMaskIntoConstraints = false
        
        contentView.addSubview(container)
        
        // Voice orb
        orbView.translatesAutoresizingMaskIntoConstraints = false
        let tapGesture = NSClickGestureRecognizer(target: self, action: #selector(orbTapped))
        orbView.addGestureRecognizer(tapGesture)
        container.addSubview(orbView)
        
        // Text field
        textField.placeholderString = "Ask Jaeger anything…"
        textField.font = .systemFont(ofSize: 15)
        textField.isBordered = false
        textField.backgroundColor = .clear
        textField.delegate = self
        textField.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(textField)
        
        // Hint label
        hintLabel.stringValue = "↵ to send · ⌘↵ for chat"
        hintLabel.font = .systemFont(ofSize: 11)
        hintLabel.textColor = .tertiaryLabelColor
        hintLabel.isBordered = false
        hintLabel.backgroundColor = .clear
        hintLabel.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(hintLabel)
        
        // Layout
        NSLayoutConstraint.activate([
            container.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 8),
            container.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 8),
            container.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -8),
            container.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -8),
            container.heightAnchor.constraint(equalToConstant: 44),
            
            orbView.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 12),
            orbView.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            orbView.widthAnchor.constraint(equalToConstant: 28),
            orbView.heightAnchor.constraint(equalToConstant: 28),
            
            textField.leadingAnchor.constraint(equalTo: orbView.trailingAnchor, constant: 12),
            textField.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -12),
            textField.topAnchor.constraint(equalTo: container.topAnchor, constant: 8),
            
            hintLabel.leadingAnchor.constraint(equalTo: textField.leadingAnchor),
            hintLabel.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -6),
        ])
    }
    
    // MARK: - Public API
    
    func show(at point: NSPoint? = nil, onSubmit: @escaping (String) -> Void, onVoiceTap: (() -> Void)? = nil) {
        self.onSubmit = onSubmit
        self.onVoiceTap = onVoiceTap
        
        guard let window = window, let screen = NSScreen.main else { return }
        
        // Position at cursor or center of screen
        let targetPoint: NSPoint
        if let point = point {
            targetPoint = point
        } else {
            let mouseLocation = NSEvent.mouseLocation
            targetPoint = NSPoint(
                x: mouseLocation.x - window.frame.width / 2,
                y: mouseLocation.y - window.frame.height - 20
            )
        }
        
        // Keep on screen
        let screenFrame = screen.visibleFrame
        let x = max(screenFrame.minX, min(targetPoint.x, screenFrame.maxX - window.frame.width))
        let y = max(screenFrame.minY, min(targetPoint.y, screenFrame.maxY - window.frame.height))
        
        window.setFrameOrigin(NSPoint(x: x, y: y))
        
        // Animate in
        window.alphaValue = 0
        window.makeKeyAndOrderFront(nil)
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            window.animator().alphaValue = 1
        }
        
        // Focus text field
        textField.stringValue = ""
        window.makeFirstResponder(textField)
        
        // Start orb in idle state
        orbView.state = .idle
    }
    
    func hide() {
        guard let window = window else { return }
        
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.15
            context.timingFunction = CAMediaTimingFunction(name: .easeIn)
            window.animator().alphaValue = 0
        } completionHandler: {
            window.orderOut(nil)
            self.orbView.state = .idle
        }
    }
    
    func setOrbState(_ state: VoiceOrbView.State) {
        orbView.state = state
    }
    
    // MARK: - Actions
    
    @objc private func orbTapped() {
        onVoiceTap?()
    }
    
    // MARK: - NSTextFieldDelegate
    
    func controlTextDidChange(_ notification: Notification) {
        // Could trigger suggestions here
    }
    
    func control(_ control: NSControl, textView: NSTextView, doCommandBy commandSelector: Selector) -> Bool {
        if commandSelector == #selector(NSResponder.insertNewline(_:)) {
            let text = textField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                onSubmit?(text)
            }
            hide()
            return true
        }
        if commandSelector == #selector(NSResponder.insertNewlineIgnoringFieldEditor(_:)) {
            // Cmd+Enter — open main chat
            onSubmit?("__OPEN_CHAT__")
            hide()
            return true
        }
        return false
    }
}

// MARK: - Voice Orb View

/// Animated gradient orb for voice visualization
final class VoiceOrbView: NSView {
    
    enum State {
        case idle
        case listening
        case processing
        case speaking
    }
    
    var state: State = .idle {
        didSet { updateAppearance() }
    }
    
    private let gradientLayer = CAGradientLayer()
    private let innerCircle = CAShapeLayer()
    private var animationTimer: Timer?
    
    override init(frame: NSRect) {
        super.init(frame: frame)
        setupLayers()
    }
    
    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setupLayers()
    }
    
    private func setupLayers() {
        wantsLayer = true
        layer?.cornerRadius = bounds.width / 2
        
        // Gradient background
        gradientLayer.frame = bounds
        gradientLayer.cornerRadius = bounds.width / 2
        gradientLayer.colors = [
            NSColor.systemBlue.cgColor,
            NSColor.systemPurple.cgColor,
            NSColor.systemPink.cgColor,
        ]
        gradientLayer.locations = [0, 0.5, 1]
        gradientLayer.startPoint = CGPoint(x: 0, y: 0)
        gradientLayer.endPoint = CGPoint(x: 1, y: 1)
        layer?.addSublayer(gradientLayer)
        
        // Inner highlight
        innerCircle.path = NSBezierPath(ovalIn: NSRect(
            x: bounds.width * 0.2,
            y: bounds.height * 0.15,
            width: bounds.width * 0.3,
            height: bounds.height * 0.2
        )).cgPath
        innerCircle.fillColor = NSColor.white.withAlphaComponent(0.4).cgColor
        layer?.addSublayer(innerCircle)
    }
    
    override func layout() {
        super.layout()
        gradientLayer.frame = bounds
        gradientLayer.cornerRadius = bounds.width / 2
    }
    
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window != nil {
            startAnimation()
        } else {
            stopAnimation()
        }
    }
    
    private func updateAppearance() {
        switch state {
        case .idle:
            gradientLayer.colors = [
                NSColor.systemBlue.cgColor,
                NSColor.systemPurple.cgColor,
            ]
            stopAnimation()
            layer?.opacity = 0.8
        case .listening:
            gradientLayer.colors = [
                NSColor.systemBlue.cgColor,
                NSColor.systemPurple.cgColor,
                NSColor.systemPink.cgColor,
            ]
            startAnimation()
            layer?.opacity = 1
        case .processing:
            gradientLayer.colors = [
                NSColor.systemPurple.cgColor,
                NSColor.systemPink.cgColor,
            ]
            startAnimation()
            layer?.opacity = 1
        case .speaking:
            gradientLayer.colors = [
                NSColor.systemGreen.cgColor,
                NSColor.systemTeal.cgColor,
            ]
            startAnimation()
            layer?.opacity = 1
        }
    }
    
    private func startAnimation() {
        stopAnimation()
        animationTimer = Timer.scheduledTimer(withTimeInterval: 1/60, repeats: true) { [weak self] _ in
            self?.animate()
        }
    }
    
    private func stopAnimation() {
        animationTimer?.invalidate()
        animationTimer = nil
    }
    
    private var animationPhase: CGFloat = 0
    
    private func animate() {
        animationPhase += 0.05
        
        // Pulse effect
        let scale = 1 + sin(animationPhase) * 0.05
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.1)
        layer?.transform = CATransform3DMakeScale(scale, scale, 1)
        CATransaction.commit()
    }
}
