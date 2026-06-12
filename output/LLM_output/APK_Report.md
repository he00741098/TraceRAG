# Final Analysis Report


## 1. Basic Information
**SHA256:** 589D0C83A01B4548B2945802F353ED80DA1F759270AB4EACF221B638843BB262


## 2. Executive Summary

The analysis of the provided Android application reveals a highly sophisticated architecture designed for evasion and the execution of hidden malicious payloads. The application functions as a **Malware Dropper/Loader**, utilizing multiple layers of obfuscation to conceal its true intent.




Key malicious behaviors identified include:

*   **Dynamic Code Loading (DCL):** The application implements a custom class loader mechanism to execute arbitrary bytecode at runtime, bypassing static analysis of the primary DEX files.
*   **JNI (Java Native Interface) Obfuscation:** Extensive use of fragmented wrapper classes and massive arrays of native methods with nonsensical names and masked parameters to hide functional logic within compiled native libraries (`.so` files).
*   **Event-Based Execution Orchestration:** The use of singleton wrappers to manage `BroadcastReceivers`, allowing the application to trigger hidden payloads in response to system events.



The core malicious functionality is decoupled from the static APK and is primarily encapsulated within native binaries and dynamically loaded modules.



## 3. Detailed Analysis


### Dynamic Code Loading and Class Loader Manipulation
**Malicious Behavior Detected: Yes**


**com.secapk.wrapper.Util**

The application utilizes a custom class loader mechanism to load and execute code that is not present in the initial application package.

*   **com.secapk.wrapper.Util.getCustomClassLoader**: This method provides a custom class loader, allowing the application to load classes from non-standard locations (e.g., private data directories or memory), which evades standard Android security scanning.
*   **com.secapk.wrapper.Util.runAll**: This method acts as an execution orchestrator, providing a structured way to trigger the payloads loaded via the custom class loader.


**Call Chain:**

`com.secapk.wrapper.Main.run()` $\rightarrow$ `com.secapk.wrapper.Util.runAll()` $\rightarrow$ `com.secapk.wrapper.Util.getCustomClassLoader()` $\rightarrow$ `[Loaded Malicious Payload]`



### JNI (Java Native Interface) Obfuscation
**Malicious Behavior Detected: Yes**


**com.secapk.wrapper.ACall**

The application uses this class as a massive, obfuscated dispatcher to native code.

*   **com.secapk.wrapper.ACall.s113 through s219**: This class contains over 100 `native` methods with identical, non-descriptive signatures: `void methodName(Object obj, Object obj2, Object obj3)`. The use of the `Object` type masks the actual data being passed (e.g., credentials, URLs, or file paths), while the nonsensical naming convention prevents functional mapping.


**com.secapk.wrapper.[Multiple Wrapper Classes]**

The application employs extreme fragmentation to hide native function calls across a vast array of classes in the `com.secapk.wrapper` package.

*   **Classes including SSSCall, TTTCall, RRRCall, etc.**: Each of these classes contains single `native` methods with randomized, short-form names (e.g., `j4`, `k4`, `i5`). By spreading these calls across dozens of unique classes, the application breaks the call chain during static analysis.


**Call Chain/Pattern:**

`Application Logic` $\rightarrow$ `com.secapk.wrapper.[ObfuscatedClass].[ObfuscatedMethod]()` $\rightarrow$ `[Hidden Native Library (.so)]`



### Event-Based Execution and Receiver Interception
**Malicious Behavior Detected: Yes**


**com.secapk.wrapper.ACall**

The application uses a singleton pattern to manage the execution of dynamically loaded components in response to system events.

*   **com.secapk.wrapper.ACall.c1/c2**: These methods, which accept `Context` and `BroadcastReceiver` parameters, are designed to register or trigger receivers that have been loaded dynamically. This allows the malware to respond to system events such as `BOOT_COMPLETED` or `SMS_RECEIVED` to execute its payload without user intervention.


**Call Chain:**

`com.secapk.wrapper.Util.runAll()` $\rightarrow$ `com.secapk.wrapper.ACall.getACall()` $\rightarrow$ `com.secapk.wrapper.ACall.c1/c2()` $\rightarrow$ `[Dynamically Loaded BroadcastReceiver]`
