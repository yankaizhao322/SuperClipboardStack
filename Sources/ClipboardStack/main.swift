import AppKit
import CryptoKit
import Foundation

private enum ClipboardPayload {
    case text(String)
    case image(NSImage, Data)

    var typeLabel: String {
        switch self {
        case .text:
            return "Text"
        case .image:
            return "Image"
        }
    }

    var displayTitle: String {
        switch self {
        case .text(let value):
            let collapsed = value
                .replacingOccurrences(of: "\n", with: " ")
                .replacingOccurrences(of: "\t", with: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if collapsed.isEmpty {
                return "Empty text"
            }
            return String(collapsed.prefix(72))
        case .image(let image, let data):
            let size = image.size
            let kb = max(1, data.count / 1024)
            return "Image \(Int(size.width))x\(Int(size.height)), \(kb) KB"
        }
    }

    var pasteboardHash: String {
        switch self {
        case .text(let value):
            return "text:" + sha256Hex(Data(value.utf8))
        case .image(_, let data):
            return "image:" + sha256Hex(data)
        }
    }

    func persisted(capturedAt: Date) -> PersistedClipboardItem {
        switch self {
        case .text(let value):
            return PersistedClipboardItem(kind: "text", text: value, imageData: nil, capturedAt: capturedAt)
        case .image(_, let data):
            return PersistedClipboardItem(kind: "image", text: nil, imageData: data, capturedAt: capturedAt)
        }
    }
}

private struct PersistedClipboardItem: Codable {
    let kind: String
    let text: String?
    let imageData: Data?
    let capturedAt: Date

    var payload: ClipboardPayload? {
        switch kind {
        case "text":
            guard let text else {
                return nil
            }
            return .text(text)
        case "image":
            guard let imageData, let image = NSImage(data: imageData) else {
                return nil
            }
            return .image(image, imageData)
        default:
            return nil
        }
    }
}

private final class ClipboardNode {
    let id = UUID()
    let hash: String
    var payload: ClipboardPayload
    var capturedAt: Date
    var previous: ClipboardNode?
    var next: ClipboardNode?

    init(payload: ClipboardPayload, capturedAt: Date = Date()) {
        self.payload = payload
        self.hash = payload.pasteboardHash
        self.capturedAt = capturedAt
    }
}

private final class ClipboardHistory {
    private let capacity: Int
    private var nodesByHash: [String: ClipboardNode] = [:]
    private var head: ClipboardNode?
    private var tail: ClipboardNode?

    init(capacity: Int) {
        self.capacity = max(1, capacity)
    }

    var count: Int {
        nodesByHash.count
    }

    func addOrPromote(_ payload: ClipboardPayload, capturedAt: Date = Date()) {
        let hash = payload.pasteboardHash
        if let existing = nodesByHash[hash] {
            existing.payload = payload
            existing.capturedAt = capturedAt
            moveToHead(existing)
            return
        }

        let node = ClipboardNode(payload: payload, capturedAt: capturedAt)
        nodesByHash[hash] = node
        insertAtHead(node)

        while nodesByHash.count > capacity, let victim = tail {
            remove(victim)
            nodesByHash.removeValue(forKey: victim.hash)
        }
    }

    func removeAll() {
        nodesByHash.removeAll()
        head = nil
        tail = nil
    }

    func snapshotNewestFirst() -> [ClipboardNode] {
        var result: [ClipboardNode] = []
        var current = head
        while let node = current {
            result.append(node)
            current = node.next
        }
        return result
    }

    func restore(newestFirst items: [PersistedClipboardItem]) {
        removeAll()
        for item in items.reversed() {
            guard let payload = item.payload else {
                continue
            }
            addOrPromote(payload, capturedAt: item.capturedAt)
        }
    }

    private func insertAtHead(_ node: ClipboardNode) {
        node.previous = nil
        node.next = head
        head?.previous = node
        head = node
        if tail == nil {
            tail = node
        }
    }

    private func moveToHead(_ node: ClipboardNode) {
        guard node !== head else {
            return
        }
        remove(node)
        insertAtHead(node)
    }

    private func remove(_ node: ClipboardNode) {
        let previous = node.previous
        let next = node.next
        previous?.next = next
        next?.previous = previous

        if node === head {
            head = next
        }
        if node === tail {
            tail = previous
        }

        node.previous = nil
        node.next = nil
    }
}

private final class ClipboardController: NSObject, NSApplicationDelegate {
    private let pasteboard = NSPasteboard.general
    private let history = ClipboardHistory(capacity: 80)
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .medium
        return formatter
    }()

    private var timer: Timer?
    private var lastChangeCount = NSPasteboard.general.changeCount
    private lazy var persistenceURL: URL = {
        let baseURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        return baseURL
            .appendingPathComponent("ClipboardStack", isDirectory: true)
            .appendingPathComponent("history.json")
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        loadHistory()
        captureCurrentPasteboard()
        timer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { [weak self] _ in
            self?.pollPasteboard()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
    }

    private func configureStatusItem() {
        statusItem.button?.title = "Clip"
        statusItem.button?.toolTip = "ClipboardStack"
        rebuildMenu()
    }

    private func pollPasteboard() {
        guard pasteboard.changeCount != lastChangeCount else {
            return
        }
        lastChangeCount = pasteboard.changeCount
        captureCurrentPasteboard()
    }

    private func captureCurrentPasteboard() {
        guard let payload = readPasteboardPayload() else {
            rebuildMenu()
            return
        }
        history.addOrPromote(payload)
        saveHistory()
        rebuildMenu()
    }

    private func readPasteboardPayload() -> ClipboardPayload? {
        if let text = pasteboard.string(forType: .string), !text.isEmpty {
            return .text(text)
        }

        if let image = NSImage(pasteboard: pasteboard),
           let tiffData = image.tiffRepresentation {
            return .image(image, tiffData)
        }

        return nil
    }

    private func rebuildMenu() {
        let menu = NSMenu()
        let header = NSMenuItem(title: "ClipboardStack (\(history.count))", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(NSMenuItem.separator())

        let nodes = history.snapshotNewestFirst()
        if nodes.isEmpty {
            let empty = NSMenuItem(title: "Copy text or image to start", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            menu.addItem(empty)
        } else {
            for (index, node) in nodes.enumerated() {
                let title = "\(index + 1). [\(node.payload.typeLabel)] \(node.payload.displayTitle)"
                let item = NSMenuItem(title: title, action: #selector(copyHistoryItem(_:)), keyEquivalent: index < 9 ? "\(index + 1)" : "")
                item.target = self
                item.representedObject = node
                item.toolTip = "Captured at \(dateFormatter.string(from: node.capturedAt)). Click to put it back on the clipboard."

                if case .image(let image, _) = node.payload {
                    item.image = makeMenuThumbnail(from: image)
                }

                menu.addItem(item)
            }
        }

        menu.addItem(NSMenuItem.separator())

        let clear = NSMenuItem(title: "Clear History", action: #selector(clearHistory), keyEquivalent: "")
        clear.target = self
        clear.isEnabled = history.count > 0
        menu.addItem(clear)

        let quit = NSMenuItem(title: "Quit ClipboardStack", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        statusItem.menu = menu
    }

    @objc private func copyHistoryItem(_ sender: NSMenuItem) {
        guard let node = sender.representedObject as? ClipboardNode else {
            return
        }

        pasteboard.clearContents()
        switch node.payload {
        case .text(let value):
            pasteboard.setString(value, forType: .string)
        case .image(let image, let data):
            pasteboard.writeObjects([image])
            pasteboard.setData(data, forType: .tiff)
        }
        lastChangeCount = pasteboard.changeCount
        history.addOrPromote(node.payload)
        saveHistory()
        rebuildMenu()
    }

    @objc private func clearHistory() {
        history.removeAll()
        saveHistory()
        rebuildMenu()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func makeMenuThumbnail(from image: NSImage) -> NSImage {
        let targetSize = NSSize(width: 18, height: 18)
        let thumbnail = NSImage(size: targetSize)
        thumbnail.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .high
        image.draw(in: NSRect(origin: .zero, size: targetSize),
                   from: NSRect(origin: .zero, size: image.size),
                   operation: .sourceOver,
                   fraction: 1.0)
        thumbnail.unlockFocus()
        thumbnail.isTemplate = false
        return thumbnail
    }

    private func loadHistory() {
        guard let data = try? Data(contentsOf: persistenceURL) else {
            return
        }

        do {
            let items = try JSONDecoder().decode([PersistedClipboardItem].self, from: data)
            history.restore(newestFirst: items)
        } catch {
            NSLog("ClipboardStack could not load history: \(error.localizedDescription)")
        }
    }

    private func saveHistory() {
        let items = history.snapshotNewestFirst().map { node in
            node.payload.persisted(capturedAt: node.capturedAt)
        }

        do {
            try FileManager.default.createDirectory(
                at: persistenceURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(items)
            try data.write(to: persistenceURL, options: .atomic)
        } catch {
            NSLog("ClipboardStack could not save history: \(error.localizedDescription)")
        }
    }
}

private func sha256Hex(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

let app = NSApplication.shared
private let delegate = ClipboardController()
app.delegate = delegate
app.run()
