import AppKit
import Foundation

final class Installer: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let pathLabel = NSTextField(wrappingLabelWithString: "")
    let stateTitle = NSTextField(labelWithString: "Checking your installation…")
    let stateDetail = NSTextField(wrappingLabelWithString: "Your original game files and saves are preserved when you install.")
    let indicator = NSProgressIndicator()
    let details = NSTextView()
    let scroll = NSScrollView()
    let disclosure = NSButton(checkboxWithTitle: "Show technical details", target: nil, action: nil)
    let eui = NSButton(checkboxWithTitle: "Enhanced User Interface (EUI)", target: nil, action: nil)
    var installButton: NSButton!
    var uninstallButton: NSButton!
    var checkButton: NSButton!
    var chooseButton: NSButton!
    var reportButton: NSButton!
    var copyButton: NSButton!
    var isBusy = false
    var installed = false
    var lastOutput = ""
    var game: URL
    let distribution: URL
    let python: URL
    let smokeDirectory: URL?

    override init() {
        let resources = Bundle.main.resourceURL!
        distribution = resources.appendingPathComponent("Distribution")
        #if arch(arm64)
        python = resources.appendingPathComponent("Runtimes/arm64/bin/python3.13")
        #else
        python = resources.appendingPathComponent("Runtimes/x86_64/bin/python3.13")
        #endif
        let defaultPath = NSHomeDirectory() + "/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app"
        game = URL(fileURLWithPath: UserDefaults.standard.string(forKey: "GamePath") ?? defaultPath)
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "--smoke-test"), arguments.count > index + 1 {
            smokeDirectory = URL(fileURLWithPath: arguments[index + 1])
        } else { smokeDirectory = nil }
        super.init()
    }

    func label(_ text: String, size: CGFloat = 13, secondary: Bool = false) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = .systemFont(ofSize: size)
        field.textColor = secondary ? .secondaryLabelColor : .labelColor
        return field
    }

    func stack(_ views: [NSView], vertical: Bool = true, spacing: CGFloat = 12) -> NSStackView {
        let view = NSStackView(views: views)
        view.orientation = vertical ? .vertical : .horizontal
        view.alignment = vertical ? .leading : .centerY
        view.spacing = spacing
        return view
    }

    func button(_ title: String, _ action: Selector) -> NSButton {
        let view = NSButton(title: title, target: self, action: action)
        view.bezelStyle = .rounded
        return view
    }

    func card(_ content: NSView) -> NSBox {
        let box = NSBox()
        box.boxType = .custom
        box.borderColor = .separatorColor
        box.fillColor = .controlBackgroundColor
        box.cornerRadius = 10
        box.contentViewMargins = NSSize(width: 16, height: 14)
        box.contentView = content
        box.heightAnchor.constraint(equalToConstant: 90).isActive = true
        return box
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        applicationItem.submenu = NSMenu()
        applicationItem.submenu!.addItem(withTitle: "About Vox Populi Mac Installer", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationItem.submenu!.addItem(.separator())
        applicationItem.submenu!.addItem(withTitle: "Quit Installer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(applicationItem)
        let edit = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        edit.submenu = NSMenu(title: "Edit")
        edit.submenu!.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.submenu!.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        menu.addItem(edit)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 720),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Vox Populi Mac Installer"
        window.delegate = self
        window.isReleasedWhenClosed = false
        let version = (try? String(contentsOf: distribution.appendingPathComponent("VERSION"), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Beta 0.1"
        let title = label("Vox Populi for Mac", size: 28)
        title.font = .systemFont(ofSize: 28, weight: .semibold)
        let subtitle = label("\(version)  ·  Single player  ·  Optional EUI", secondary: true)
        let globe = NSImageView(image: NSImage(systemSymbolName: "globe", accessibilityDescription: nil)!)
        globe.contentTintColor = .systemIndigo
        globe.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 42, weight: .regular)
        globe.widthAnchor.constraint(equalToConstant: 52).isActive = true
        let header = stack([globe, stack([title, subtitle], spacing: 4)], vertical: false, spacing: 16)
        let introduction = label("Install Vox Populi’s AI, balance changes and interface for Civilization V: Brave New World.")
        eui.target = self
        eui.action = #selector(interfaceChanged)
        eui.state = CommandLine.arguments.contains("--eui") ? .on : .off
        let interfaceChoice = stack([eui, label("Bundled VP-compatible version · Experimental", size: 12, secondary: true)], vertical: false, spacing: 12)

        chooseButton = button("Choose Game…", #selector(chooseGame))
        pathLabel.font = .systemFont(ofSize: 12)
        pathLabel.textColor = .secondaryLabelColor
        pathLabel.isSelectable = true
        pathLabel.lineBreakMode = .byTruncatingMiddle
        pathLabel.maximumNumberOfLines = 2
        pathLabel.widthAnchor.constraint(equalToConstant: 555).isActive = true
        let gameHeading = label("Civilization V location", size: 13)
        gameHeading.font = .systemFont(ofSize: 13, weight: .semibold)
        let gameCard = card(stack([gameHeading, stack([pathLabel, chooseButton], vertical: false)]))

        indicator.style = .spinning
        indicator.controlSize = .small
        indicator.isDisplayedWhenStopped = false
        stateTitle.font = .systemFont(ofSize: 16, weight: .semibold)
        stateDetail.font = .systemFont(ofSize: 13)
        stateDetail.textColor = .secondaryLabelColor
        stateDetail.preferredMaxLayoutWidth = 680
        let stateCard = card(stack([stack([indicator, stateTitle], vertical: false, spacing: 8), stateDetail], spacing: 7))

        installButton = button("Install Beta", #selector(installBeta))
        installButton.keyEquivalent = "\r"
        installButton.contentTintColor = .systemIndigo
        checkButton = button("Check Compatibility", #selector(checkCompatibility))
        uninstallButton = button("Uninstall / Restore", #selector(uninstallBeta))
        let actions = stack([installButton, checkButton, uninstallButton], vertical: false, spacing: 10)

        let notice = label("Quit Civ V and its launcher. Move separate EUI / VPUI copies and other VP modpacks outside DLC. Startup videos and publisher logos are skipped; original files, saves and the intro setting return when you uninstall. Restore first to change interfaces.", secondary: true)
        let mods = label("Why not the MODS folder? Mac Civ V has its own game core, but cannot load Vox Populi’s Windows DLL. This installer replaces the core with a native Mac VP version and installs its matching startup data, with backups. VP stays active until you uninstall.", secondary: true)
        notice.preferredMaxLayoutWidth = 760
        mods.preferredMaxLayoutWidth = 760
        reportButton = button("Diagnostics", #selector(report))
        copyButton = button("Copy Details", #selector(copyDetails))
        let readme = button("Read Installation Guide", #selector(openReadme))
        let support = stack([readme, reportButton, copyButton], vertical: false, spacing: 8)

        disclosure.target = self
        disclosure.action = #selector(toggleDetails)
        details.isEditable = false
        details.isSelectable = true
        details.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        details.textContainerInset = NSSize(width: 8, height: 8)
        details.autoresizingMask = [.width]
        scroll.documentView = details
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.isHidden = true
        scroll.heightAnchor.constraint(equalToConstant: 150).isActive = true

        let content = stack([header, introduction, gameCard, interfaceChoice, stateCard, actions, notice, mods, support, disclosure, scroll], spacing: 15)
        content.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 26),
            content.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -26),
            content.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24)
        ])
        for view in [introduction, gameCard, stateCard, notice, mods, scroll] {
            view.widthAnchor.constraint(equalTo: content.widthAnchor).isActive = true
        }
        pathLabel.stringValue = game.path
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        NSApp.applicationIconImage = NSImage(systemSymbolName: "globe", accessibilityDescription: "Vox Populi")
        if let directory = smokeDirectory {
            window.contentView!.layoutSubtreeIfNeeded()
            render(to: directory)
            perform("install", dryRun: true) { code, _ in
                let result: [String: Any] = ["preflightExitCode": code, "installEnabled": self.installButton.isEnabled,
                                            "euiSelected": self.eui.state == .on, "euiEnabled": self.eui.isEnabled,
                                            "uninstallEnabled": self.uninstallButton.isEnabled,
                                            "title": self.stateTitle.stringValue, "detail": self.stateDetail.stringValue]
                if let data = try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys]) {
                    try? data.write(to: directory.appendingPathComponent("gui-smoke.json"))
                }
                self.disclosure.state = .on
                self.toggleDetails()
                self.window.contentView!.layoutSubtreeIfNeeded()
                self.render(to: directory, filename: "installer-details.png")
                NSApp.terminate(nil)
            }
        } else { refresh() }
    }

    func setBusy(_ busy: Bool) {
        isBusy = busy
        [installButton, uninstallButton, checkButton, chooseButton, reportButton, copyButton].forEach { $0?.isEnabled = !busy }
        installButton.isEnabled = !busy && !installed
        checkButton.isEnabled = !busy && !installed
        eui.isEnabled = !busy && !installed
        if busy { indicator.startAnimation(nil) } else { indicator.stopAnimation(nil) }
    }

    func perform(_ command: String, dryRun: Bool = false, completion: ((Int32, String) -> Void)? = nil) {
        guard !isBusy else { return }
        setBusy(true)
        stateTitle.stringValue = dryRun ? "Checking compatibility…" : ["install": "Installing Vox Populi…", "uninstall": "Restoring your original game…", "status": "Checking your installation…", "report": "Collecting diagnostics…"][command]!
        stateDetail.stringValue = "Please keep this window open."
        let interpreter = python, cli = distribution.appendingPathComponent("vp-mac.py"), selectedGame = game
        let useEUI = command == "install" && eui.state == .on
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(), pipe = Pipe()
            process.executableURL = interpreter
            process.arguments = ["-I", "-B", cli.path, command, "--app", selectedGame.path] + (useEUI ? ["--eui"] : []) + (dryRun ? ["--dry-run"] : [])
            var environment = ProcessInfo.processInfo.environment
            for key in ["PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES"] { environment.removeValue(forKey: key) }
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONNOUSERSITE"] = "1"
            environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
            process.environment = environment
            process.standardOutput = pipe
            process.standardError = pipe
            var code: Int32 = 1, output = ""
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                output = String(decoding: data, as: UTF8.self)
                code = process.terminationStatus
            } catch { output = "Could not start the bundled installer: \(error.localizedDescription). Extract the complete app and try again." }
            DispatchQueue.main.async {
                self.lastOutput = output
                self.details.string = output
                if code == 0 { self.succeeded(command, dryRun: dryRun, output: output) }
                else { self.failed(output) }
                self.setBusy(false)
                completion?(code, output)
            }
        }
    }

    func succeeded(_ command: String, dryRun: Bool, output: String) {
        if dryRun {
            stateTitle.stringValue = "Ready to install"
            stateDetail.stringValue = "\(eui.state == .on ? "VP with EUI" : "Standard VP") is ready. Startup videos and logos will be skipped, with originals preserved for uninstall."
        } else if command == "install" {
            installed = true
            stateTitle.stringValue = "Vox Populi is installed"
            stateDetail.stringValue = "\(eui.state == .on ? "VP with EUI" : "Standard VP") is active. Launch from Steam and start a NEW regular Single Player game."
        } else if command == "uninstall" {
            installed = false
            let unchanged = output.contains("No managed probe is installed")
            stateTitle.stringValue = unchanged ? "Your original game is already active" : "Your original game is restored"
            stateDetail.stringValue = unchanged ? "There was no managed beta to remove. No files were changed." : "Your normal saves are back. Beta saves and cache were preserved separately; see Details for their locations."
        } else if let data = output.data(using: .utf8), let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if command == "status" {
                let state = json["state"] as? String ?? "unknown"
                installed = state == "installed"
                if installed { eui.state = json["interface"] as? String == "eui" ? .on : .off }
                stateTitle.stringValue = installed ? "Vox Populi is installed" : state == "stock" ? "Original Civ V is installed" : "An existing installation needs attention"
                stateDetail.stringValue = installed ? "\(eui.state == .on ? "VP with EUI" : "Standard VP") is active. To change interfaces, Uninstall / Restore first." : state == "stock" ? "Choose your interface, then Check Compatibility or Install Beta. Close Civ V first." : "Keep the backups. Uninstall / Restore will check them before changing anything."
            } else {
                stateTitle.stringValue = "Diagnostics collected"
                stateDetail.stringValue = "Open or copy Details when reporting a problem. Last startup result: \(json["startup_result"] as? String ?? "not available")."
                disclosure.state = .on
                toggleDetails()
            }
        }
    }

    func failed(_ output: String) {
        var title = "Setup needs attention"
        var detail = "No successful installation was reported. Open Details for the exact message. If an installation was interrupted, use Uninstall / Restore."
        if !FileManager.default.fileExists(atPath: python.path) { title = "Installer files are missing"; detail = "Extract the complete macOS ZIP and open the app again. Keep the app bundle intact." }
        else if !FileManager.default.fileExists(atPath: game.appendingPathComponent("Contents/MacOS/Civilization V").path) { title = "Choose your Civilization V app"; detail = "Click Choose Game and select Civilization V.app in your Steam library. In Steam, Installed Files → Browse opens the game's folder." }
        else if output.contains("Quit Civ V") { title = "Close Civ V first"; detail = "Quit both Civilization V and its launcher, then try again. Steam can stay open." }
        else if output.contains("Separate EUI / VPUI") || output.contains("existing VP_MODPACK") || output.contains("existing package uses") { title = "Another mod conflicts with this beta"; detail = "Move separate EUI / VPUI copies or the other VP modpack completely outside DLC. Select EUI here to install the bundled matching version." }
        else if output.contains("Restore the previous") || output.contains("Restore it before installing") { title = "Restore the installed beta first"; detail = "Click Uninstall / Restore, then choose your interface and install. Beta saves are preserved separately. Start a new game after switching interfaces." }
        else if output.contains("reviewed SHA-256") { title = "This game build is not supported"; detail = "Beta 0.1 requires Steam's Mac Aspyr 1.4.2 (180925) build. Your game files were not replaced." }
        else if output.contains("localization cache") || output.contains("Localization-Merged.db") { title = "Run normal Brave New World once"; detail = "Restore any existing beta, launch unmodified BNW, reach the menu and quit. Then try installing again." }
        else if output.contains("no unique GameSettings") || (output.contains("UserSettings.ini") && output.contains("Expected a regular file")) { title = "Run normal Brave New World once"; detail = "The installer needs the game's UserSettings.ini to manage startup video skipping. Restore, launch normal BNW once and quit, then retry." }
        else if output.contains("Permission denied") || output.contains("Operation not permitted") { title = "macOS blocked file access"; detail = "Use Choose Game to select the app again. Check the exact blocked path in Details before changing permissions." }
        stateTitle.stringValue = title
        stateDetail.stringValue = detail
        disclosure.state = .on
        toggleDetails()
    }

    @objc func chooseGame() {
        let panel = NSOpenPanel()
        panel.title = "Choose Civilization V.app"
        panel.message = "In Steam, use Installed Files → Browse to find the game app."
        panel.allowedFileTypes = ["app"]
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.directoryURL = game.deletingLastPathComponent()
        panel.beginSheetModal(for: window) { response in
            guard response == .OK, let url = panel.url else { return }
            self.game = url
            self.pathLabel.stringValue = url.path
            UserDefaults.standard.set(url.path, forKey: "GamePath")
            self.installed = false
            self.refresh()
        }
    }
    @objc func installBeta() { perform("install") }
    @objc func interfaceChanged() {
        stateTitle.stringValue = eui.state == .on ? "EUI selected" : "Standard interface selected"
        stateDetail.stringValue = "Click Check Compatibility to check this selection. EUI includes the matching VP compatibility files."
    }
    @objc func uninstallBeta() { perform("uninstall") }
    @objc func checkCompatibility() { perform("install", dryRun: true) }
    @objc func refresh() { perform("status") }
    @objc func report() { perform("report") }
    @objc func copyDetails() { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(lastOutput, forType: .string) }
    @objc func openReadme() { NSWorkspace.shared.open(distribution.appendingPathComponent("Installation Guide.html")) }
    @objc func toggleDetails() {
        scroll.isHidden = disclosure.state != .on
        let available = NSScreen.main?.visibleFrame.height ?? 1000
        window.setContentSize(NSSize(width: 820, height: min(scroll.isHidden ? 720 : 885, available - 60)))
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { !isBusy }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { isBusy ? .terminateCancel : .terminateNow }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func render(to directory: URL, filename: String = "installer.png") {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        guard let view = window.contentView, let image = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return }
        view.cacheDisplay(in: view.bounds, to: image)
        let composite = NSImage(size: view.bounds.size)
        composite.lockFocus()
        window.effectiveAppearance.performAsCurrentDrawingAppearance {
            NSColor.windowBackgroundColor.setFill()
            NSBezierPath(rect: view.bounds).fill()
            let capture = NSImage(size: view.bounds.size)
            capture.addRepresentation(image)
            capture.draw(in: view.bounds, from: .zero, operation: .sourceOver, fraction: 1)
        }
        composite.unlockFocus()
        if let tiff = composite.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
           let data = bitmap.representation(using: .png, properties: [:]) {
            try? data.write(to: directory.appendingPathComponent(filename))
        }
    }
}

let app = NSApplication.shared
let delegate = Installer()
app.delegate = delegate
app.run()
