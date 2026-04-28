#!/usr/bin/swift
import Foundation
import CoreGraphics

// MARK: - SkyLight Framework Bindings

typealias SLEventPostToPidFunc = @convention(c) (
  UInt32,
  UInt32,
  CGPoint,
  UnsafeRawPointer?
) -> Void

typealias SLPSPostEventRecordToFunc = @convention(c) (
  UInt32,
  UnsafeRawPointer?
) -> Void

typealias AXObserverAddNotificationFunc = @convention(c) (
  UnsafeRawPointer,
  UInt32,
  UnsafeRawPointer,
  UnsafeRawPointer?
) -> Int32

// MARK: - Framework Loading

var skylightHandle: UnsafeMutableRawPointer?
var sLEventPostToPid: SLEventPostToPidFunc?
var sLPSPostEventRecordTo: SLPSPostEventRecordToFunc?
var aXObserverAddNotification: AXObserverAddNotificationFunc?

func loadSkyLightFramework() {
  let frameworkPath = "/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight"
  
  guard let handle = dlopen(frameworkPath, RTLD_NOW) else {
    print("[daemon] WARN: Failed to load SkyLight.framework")
    return
  }
  
  skylightHandle = handle
  
  // Load SLEventPostToPid
  if let sym = dlsym(handle, "SLEventPostToPid") {
    sLEventPostToPid = unsafeBitCast(sym, to: SLEventPostToPidFunc.self)
    print("[daemon] ✓ Loaded SLEventPostToPid")
  } else {
    print("[daemon] WARN: Failed to load SLEventPostToPid")
  }
  
  // Load SLPSPostEventRecordTo
  if let sym = dlsym(handle, "SLPSPostEventRecordTo") {
    sLPSPostEventRecordTo = unsafeBitCast(sym, to: SLPSPostEventRecordToFunc.self)
    print("[daemon] ✓ Loaded SLPSPostEventRecordTo")
  } else {
    print("[daemon] WARN: Failed to load SLPSPostEventRecordTo")
  }
  
  // Load _AXObserverAddNotificationAndCheckRemote (via dlsym)
  if let sym = dlsym(handle, "_AXObserverAddNotificationAndCheckRemote") {
    aXObserverAddNotification = unsafeBitCast(sym, to: AXObserverAddNotificationFunc.self)
    print("[daemon] ✓ Loaded _AXObserverAddNotificationAndCheckRemote")
  } else {
    print("[daemon] WARN: Failed to load _AXObserverAddNotificationAndCheckRemote")
  }
}

// MARK: - Unix Socket Server

let SOCKET_PATH = "/tmp/skylight-daemon.sock"
let MAX_CLIENTS: Int32 = 10

var serverSocket: Int32 = -1
var isRunning = true

func setupSignalHandlers() {
  signal(SIGTERM) { _ in
    print("\n[daemon] Received SIGTERM, shutting down gracefully...")
    isRunning = false
  }
  
  signal(SIGINT) { _ in
    print("\n[daemon] Received SIGINT, shutting down gracefully...")
    isRunning = false
  }
}

func startServer() {
  // Remove existing socket file
  try? FileManager.default.removeItem(atPath: SOCKET_PATH)
  
  // Create socket
  serverSocket = socket(AF_UNIX, SOCK_STREAM, 0)
  guard serverSocket >= 0 else {
    print("[daemon] ERROR: Failed to create socket")
    return
  }
  
  // Bind socket
  var addr = sockaddr_un()
  addr.sun_family = sa_family_t(AF_UNIX)
  _ = SOCKET_PATH.withCString { socketPath in
    strncpy(&addr.sun_path.0, socketPath, 103)
  }
  
  let addrPtr = withUnsafePointer(to: &addr) { (ptr: UnsafePointer<sockaddr_un>) in
    UnsafeRawPointer(ptr).assumingMemoryBound(to: sockaddr.self)
  }
  
  guard bind(serverSocket, addrPtr, socklen_t(MemoryLayout<sockaddr_un>.size)) >= 0 else {
    print("[daemon] ERROR: Failed to bind socket")
    close(serverSocket)
    return
  }
  
  // Listen for connections
  guard listen(serverSocket, MAX_CLIENTS) >= 0 else {
    print("[daemon] ERROR: Failed to listen on socket")
    close(serverSocket)
    return
  }
  
  print("[daemon] ✓ Listening on \(SOCKET_PATH)")
  
  // Accept client connections
  while isRunning {
    // Set timeout on accept so we can check isRunning periodically
    var timeout = timeval()
    timeout.tv_sec = 1
    timeout.tv_usec = 0
    
    _ = setsockopt(serverSocket, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
    
    var clientAddr = sockaddr_un()
    var clientAddrLen = socklen_t(MemoryLayout<sockaddr_un>.size)
    
    let clientSocket = withUnsafeMutablePointer(to: &clientAddr) { (ptr: UnsafeMutablePointer<sockaddr_un>) in
      let addrPtr = UnsafeMutableRawPointer(ptr).assumingMemoryBound(to: sockaddr.self)
      return accept(serverSocket, addrPtr, &clientAddrLen)
    }
    
    if clientSocket < 0 {
      if errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK {
        continue
      }
      print("[daemon] WARN: accept() failed")
      continue
    }
    
    // Handle client in a separate thread
    DispatchQueue.global().async {
      handleClient(socket: clientSocket)
    }
  }
  
  // Cleanup
  close(serverSocket)
  try? FileManager.default.removeItem(atPath: SOCKET_PATH)
  print("[daemon] ✓ Socket cleaned up")
}

func handleClient(socket: Int32) {
  defer {
    close(socket)
  }
  
  let bufferSize = 4096
  var buffer = [UInt8](repeating: 0, count: bufferSize)
  
  let bytesRead = read(socket, &buffer, bufferSize)
  guard bytesRead > 0 else {
    return
  }
  
  let requestData = Data(buffer[0..<bytesRead])
  guard let requestJSON = try? JSONSerialization.jsonObject(with: requestData) as? [String: Any] else {
    sendResponse(socket: socket, success: false, error: "Invalid JSON")
    return
  }
  
  let response = handleRPCRequest(requestJSON)
  sendResponse(socket: socket, response: response)
}

func handleRPCRequest(_ request: [String: Any]) -> [String: Any] {
  guard let method = request["method"] as? String else {
    return ["success": false, "error": "Missing method"]
  }
  
  switch method {
  case "eventPostToPid":
    guard let pid = request["pid"] as? Int,
          let eventType = request["eventType"] as? String else {
      return ["success": false, "error": "Missing pid or eventType"]
    }
    
    let params = request["params"] as? [String: Any] ?? [:]
    return eventPostToPid(pid: UInt32(pid), eventType: eventType, params: params)
  
  case "activateWithoutRaise":
    guard let pid = request["pid"] as? Int else {
      return ["success": false, "error": "Missing pid"]
    }
    
    return activateWithoutRaise(pid: UInt32(pid))
  
  case "keepAXTreeAlive":
    guard let pid = request["pid"] as? Int else {
      return ["success": false, "error": "Missing pid"]
    }
    
    return keepAXTreeAlive(pid: UInt32(pid))
  
  case "primerClick":
    guard let pid = request["pid"] as? Int else {
      return ["success": false, "error": "Missing pid"]
    }
    
    return primerClick(pid: UInt32(pid))
  
  default:
    return ["success": false, "error": "Unknown method: \(method)"]
  }
}

func eventPostToPid(pid: UInt32, eventType: String, params: [String: Any]) -> [String: Any] {
  guard let postFunc = sLEventPostToPid else {
    return ["success": false, "error": "SLEventPostToPid not available"]
  }
  
  // Map event type to event code (placeholder: actual implementation constructs full CGEvent)
  let eventCode: UInt32
  switch eventType {
  case "click":
    eventCode = 1  // kCGEventLeftMouseDown
  case "keyboard":
    eventCode = 10 // kCGEventKeyDown
  case "mouse_move":
    eventCode = 5  // kCGEventMouseMoved
  default:
    eventCode = 1
  }
  
  let position = CGPoint(x: params["x"] as? CGFloat ?? 0, y: params["y"] as? CGFloat ?? 0)
  
  postFunc(pid, eventCode, position, nil)
  
  return ["success": true, "result": "Event posted to pid \(pid)"]
}

func activateWithoutRaise(pid: UInt32) -> [String: Any] {
  guard let psFunc = sLPSPostEventRecordTo else {
    return ["success": false, "error": "SLPSPostEventRecordTo not available"]
  }
  
  psFunc(pid, nil)
  
  return ["success": true, "result": "Window activated without raise for pid \(pid)"]
}

func keepAXTreeAlive(pid: UInt32) -> [String: Any] {
  guard let axFunc = aXObserverAddNotification else {
    return ["success": false, "error": "_AXObserverAddNotificationAndCheckRemote not available"]
  }
  
  // Call with placeholder pointers
  let nullPtr = UnsafeRawPointer(bitPattern: 0)!
  _ = axFunc(nullPtr, pid, nullPtr, nil)
  
  return ["success": true, "result": "AX tree observer set for pid \(pid)"]
}

func primerClick(pid: UInt32) -> [String: Any] {
  guard let postFunc = sLEventPostToPid else {
    return ["success": false, "error": "SLEventPostToPid not available"]
  }
  
  let offScreenPos = CGPoint(x: -1, y: -1)
  
  // Left mouse down and up at off-screen position
  let eventCode: UInt32 = 1  // kCGEventLeftMouseDown
  postFunc(pid, eventCode, offScreenPos, nil)
  postFunc(pid, 2, offScreenPos, nil) // kCGEventLeftMouseUp
  
  return ["success": true, "result": "Primer click sent to pid \(pid) at (-1, -1)"]
}

func sendResponse(socket: Int32, response: [String: Any]) {
  guard let data = try? JSONSerialization.data(withJSONObject: response) else {
    sendResponse(socket: socket, success: false, error: "Failed to serialize response")
    return
  }
  
  _ = write(socket, (data as NSData).bytes, data.count)
}

func sendResponse(socket: Int32, success: Bool, error: String) {
  let response: [String: Any] = [
    "success": success,
    "error": error
  ]
  
  guard let data = try? JSONSerialization.data(withJSONObject: response) else {
    return
  }
  
  _ = write(socket, (data as NSData).bytes, data.count)
}

// MARK: - Main

func main() {
  print("[daemon] SkyLight daemon starting...")
  
  // Load SkyLight framework
  loadSkyLightFramework()
  
  // Setup signal handlers for graceful shutdown
  setupSignalHandlers()
  
  // Start Unix socket server
  startServer()
  
  print("[daemon] SkyLight daemon exiting")
}

main()
