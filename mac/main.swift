import AppKit
import Darwin

/// Dock app that starts the local server and opens the page.
/// Quit stops the server. A second click brings the page back.
private let delegate = AppDelegate()

let app = NSApplication.shared
app.setActivationPolicy(.regular)
installMenu(app)
app.delegate = delegate
app.run()

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var root = ""
    private var server: Process?
    private var logHandle: FileHandle?
    private var adoptedPID: Int32?
    private var busy = false
    private var stopping = false
    private var termSource: DispatchSourceSignal?
    private var pendingPaths: [String] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        source.setEventHandler { NSApp.terminate(nil) }
        termSource = source
        source.resume()
        bringUp()
        deliverFiles()
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        pendingPaths.append(contentsOf: urls.map(\.path))
        if busy { return }
        if root.isEmpty { root = projectRoot() }
        if liveServerPID() != nil {
            openPage()
            deliverFiles()
            return
        }
        bringUp()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        bringUp()
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        stopServer()
        return .terminateNow
    }

    @objc func openAgain(_ sender: Any?) {
        bringUp()
    }

    private func bringUp() {
        if busy { return }
        if root.isEmpty { root = projectRoot() }
        if let pid = liveServerPID() {
            if server?.isRunning != true { adoptedPID = pid }
            openPage()
            return
        }
        busy = true
        startServer()
        busy = false
    }

    private func startServer() {
        root = projectRoot()
        let marker = (root as NSString).appendingPathComponent("run.sh")
        guard FileManager.default.isExecutableFile(atPath: marker) else {
            fail("Image Utilities couldn't find its folder.")
            return
        }
        guard ensurePython() else {
            fail("Image Utilities couldn't set up Python. See var/launch.log in the project folder.")
            return
        }
        clearSessionFiles()
        guard launchPython() else { return }
        guard waitForURL(seconds: 120) else {
            let detail = logTail()
            stopServer()
            let extra = detail.isEmpty ? "" : "\n\n\(detail)"
            fail("Image Utilities stopped while starting.\(extra)")
            return
        }
        openPage()
        deliverFiles()
    }

    private func ensurePython() -> Bool {
        let python = pythonPath()
        if FileManager.default.isExecutableFile(atPath: python) { return true }
        guard let log = openLog() else { return false }
        let setup = Process()
        setup.executableURL = URL(fileURLWithPath: "/bin/bash")
        setup.currentDirectoryURL = URL(fileURLWithPath: root)
        setup.arguments = [
            "-c",
            "set -euo pipefail; uv venv --python 3.12 .venv; uv pip install --python .venv/bin/python -r requirements.txt",
        ]
        var env = ProcessInfo.processInfo.environment
        let home = NSHomeDirectory()
        env["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "")
        setup.environment = env
        setup.standardOutput = log
        setup.standardError = log
        do {
            try setup.run()
        } catch {
            return false
        }
        setup.waitUntilExit()
        return setup.terminationStatus == 0 && FileManager.default.isExecutableFile(atPath: python)
    }

    private func launchPython() -> Bool {
        guard let log = openLog() else {
            fail("Image Utilities couldn't write its log.")
            return false
        }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: pythonPath())
        proc.arguments = ["-m", "app", "--no-browser"]
        proc.currentDirectoryURL = URL(fileURLWithPath: root)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = root
        proc.environment = env
        proc.standardInput = FileHandle.nullDevice
        proc.standardOutput = log
        proc.standardError = log
        server = proc
        adoptedPID = nil
        do {
            try proc.run()
        } catch {
            fail("Image Utilities couldn't start.\n\n\(error.localizedDescription)")
            return false
        }
        return true
    }

    private func waitForURL(seconds: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline {
            if readURL() != nil { return true }
            if let proc = server, !proc.isRunning { return false }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return readURL() != nil
    }

    private func deliverFiles() {
        guard !pendingPaths.isEmpty, let page = readURL() else { return }
        let paths = pendingPaths
        pendingPaths.removeAll()
        var base = page.absoluteString
        if base.hasSuffix("/") { base.removeLast() }
        guard let endpoint = URL(string: base + "/api/open") else { return }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["paths": paths])
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard code >= 400 else { return }
            var message = "Those pictures couldn't be opened."
            if let data, let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = object["detail"] as? String, !detail.isEmpty {
                message = detail
            }
            DispatchQueue.main.async { self.warn(message) }
        }.resume()
    }

    private func openPage() {
        if ProcessInfo.processInfo.environment["IMAGE_UTILITIES_NO_BROWSER"] == "1" { return }
        guard let url = readURL(), url.host == "127.0.0.1" || url.host == "localhost" else { return }
        NSWorkspace.shared.open(url)
    }

    private func stopServer() {
        if stopping { return }
        stopping = true
        let pid = server?.isRunning == true ? server?.processIdentifier : (adoptedPID ?? readPID())
        guard let pid, isOurServer(pid) else { return }
        kill(pid, SIGTERM)
        let deadline = Date().addingTimeInterval(8)
        while isAlive(pid), Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        if isAlive(pid), isOurServer(pid) {
            kill(pid, SIGKILL)
        }
        if !isAlive(pid) {
            clearSessionFiles()
        }
    }

    private func liveServerPID() -> Int32? {
        if let proc = server, proc.isRunning, isOurServer(proc.processIdentifier) {
            return proc.processIdentifier
        }
        if let pid = readPID(), isOurServer(pid) { return pid }
        return nil
    }

    private func readPID() -> Int32? {
        let path = (root as NSString).appendingPathComponent("var/app.pid")
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        return Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func readURL() -> URL? {
        let path = (root as NSString).appendingPathComponent("var/app.url")
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return nil }
        return URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func clearSessionFiles() {
        for name in ["app.pid", "app.url"] {
            let path = (root as NSString).appendingPathComponent("var/\(name)")
            try? FileManager.default.removeItem(atPath: path)
        }
    }

    private func isAlive(_ pid: Int32) -> Bool {
        pid > 0 && kill(pid, 0) == 0
    }

    private func isOurServer(_ pid: Int32) -> Bool {
        guard isAlive(pid) else { return false }
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-p", String(pid), "-o", "command="]
        let pipe = Pipe()
        ps.standardOutput = pipe
        do { try ps.run() } catch { return false }
        ps.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let command = String(data: data, encoding: .utf8) ?? ""
        return command.contains("Image_Utilities") && command.contains("-m app")
    }

    private func pythonPath() -> String {
        (root as NSString).appendingPathComponent(".venv/bin/python")
    }

    private func openLog() -> FileHandle? {
        let dir = (root as NSString).appendingPathComponent("var")
        let path = (dir as NSString).appendingPathComponent("launch.log")
        do {
            try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: path) {
                FileManager.default.createFile(atPath: path, contents: nil)
            }
            let handle = try FileHandle(forWritingTo: URL(fileURLWithPath: path))
            try handle.seekToEnd()
            if let stamp = "----- \(Date()) -----\n".data(using: .utf8) {
                try handle.write(contentsOf: stamp)
            }
            logHandle = handle
            return handle
        } catch {
            return nil
        }
    }

    private func logTail() -> String {
        let path = (root as NSString).appendingPathComponent("var/launch.log")
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return "" }
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).suffix(8)
        let joined = lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        if joined.count <= 500 { return joined }
        return String(joined.suffix(500))
    }

    private func warn(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Image Utilities"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func fail(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Image Utilities"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
        NSApp.terminate(nil)
    }
}

private func projectRoot() -> String {
    let bundle = Bundle.main.bundleURL
    let candidates = [
        bundle.deletingLastPathComponent().path,
        bundle.deletingLastPathComponent().deletingLastPathComponent().path,
        "/Users/jose/Documents/Git/Image_Utilities",
    ]
    for candidate in candidates {
        let marker = (candidate as NSString).appendingPathComponent("run.sh")
        if FileManager.default.isExecutableFile(atPath: marker) { return candidate }
    }
    return "/Users/jose/Documents/Git/Image_Utilities"
}

private func installMenu(_ app: NSApplication) {
    let main = NSMenu()
    let appItem = NSMenuItem()
    main.addItem(appItem)
    let appMenu = NSMenu()
    appItem.submenu = appMenu
    let openItem = NSMenuItem(
        title: "Open Image Utilities",
        action: #selector(AppDelegate.openAgain(_:)),
        keyEquivalent: "o"
    )
    openItem.target = delegate
    appMenu.addItem(openItem)
    appMenu.addItem(.separator())
    appMenu.addItem(
        NSMenuItem(title: "Quit Image Utilities", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
    )
    app.mainMenu = main
}
