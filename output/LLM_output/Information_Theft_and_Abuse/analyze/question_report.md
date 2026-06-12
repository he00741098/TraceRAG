# Malware Analysis Report


## Overall Summary

The analyzed application exhibits sophisticated behaviors characteristic of a **malicious loader or dropper**. The application employs a multi-layered strategy to evade detection, including the use of a custom wrapper to dynamically load secondary payloads via `DexClassLoader`, the implementation of a dynamic proxy mechanism for `BroadcastReceivers` to hide execution flow, and the heavy delegation of sensitive operations to native (JNI) methods. Furthermore, the application actively collects device metadata (package name, APK path, and process name) and system information (CPU details) and uses Java Reflection to bypass access controls, all of which are indicative of a coordinated effort for information theft and unauthorized code execution.



## Behavior Analysis Sections


**com.secapk.wrapper.ApplicationWrapper**

The `com.secapk.wrapper.ApplicationWrapper` class implements a custom initialization routine in its `onCreate` method. It utilizes a `DexClassLoader` to dynamically load a class named `com.secapk.wrapper.FirstApplication`. Once loaded, it instantiates this class and invokes its `onCreate()` method. This pattern is used to separate the initial application entry point from the actual functional logic, allowing the primary malicious payload to be loaded dynamically from a separate DEX file at runtime.



**com.secapk.wrapper.Util**

The `com.secapk.wrapper.Util` class contains several methods used for information gathering and process manipulation:

*   **`createChildProcess`**: This method retrieves the application's source directory (the path to the APK file) and its package name, passing them as byte arrays to the native method `ACall.r1`. This is a strong indicator of attempting to spawn child processes or execute secondary payloads from the native layer.
*   **`tryDo`**: This method retrieves the application's package name, the absolute file path of the APK (`sourceDir`), and the current process name, passing them to the native method `ACall.r2`. This gathers environmental identifiers used to identify the target or prepare for exfiltrating the APK.
*   **`getCPUinfo`**: This method executes the system command `/system/bin/cat /proc/cpuinfo` via `ProcessBuilder` to retrieve hardware specifications for device fingerprinting.
*   **`getField` & `getFieldValue`**: These methods use Java Reflection to bypass access control. `getField` explicitly calls `field.setAccessible(true)`, allowing the application to extract sensitive data stored in `private` or `protected` fields of various objects.
*   **`toASC`**: This method converts byte arrays into a hexadecimal representation, commonly used to format stolen data for exfiltration or to avoid detection by string-based security filters.
*   **`checkUpdate`**: This method manages hidden directories (`.cache/`) and files (`.sec_version`) within the application's private data directory, a typical pattern for managing downloaded malicious components.


**com.secapk.wrapper.ACall**

The `com.secapk.wrapper.ACall` class serves as the primary interface for hidden logic through numerous `native` method declarations (e.g., `at1`, `set2`, `r1`, `r2`, `set4`, `set5`, `c1`, `c2`). By implementing core logic in a compiled C/C++ library (JNI), the application obscures its true intent, making it difficult for static analysis tools and automated sandboxes to trace the execution flow or identify data exfiltration mechanisms.



**com.slpresent.LMR.LMR**

The `com.slpresent.LMR.LMR` class implements a dynamic proxy pattern within its `onReceive` method. It uses a custom class loader to dynamically instantiate a `BroadcastReceiver`. Crucially, it wraps the execution of this `realReceiver` with native calls: `ACall.getACall().c1(...)` before execution and `ACall.getACall().c2(...)` after execution. This structure is designed to intercept or monitor the dynamically loaded component's execution via the native layer, effectively hiding the malicious payload's activity from the Java runtime.



## Malicious Call Chain


**1. Dynamic Payload Execution & Native Hooking Chain:**

`com.secapk.wrapper.ApplicationWrapper.onCreate()`


$\rightarrow$ `com.secapk.wrapper.Util.getCustomClassLoader()` (Dynamic Loading)


$\rightarrow$ `com.secapk.wrapper.FirstApplication.onCreate()`


$\rightarrow$ `com.slpresent.LMR.LMR.onReceive()`


$\rightarrow$ `com.secapk.wrapper.ACall.c1()` (Native Hook/Pre-execution)


$\rightarrow$ `[Dynamically Loaded Receiver].onReceive()` (Payload Execution)


$\rightarrow$ `com.secapk.wrapper.ACall.c2()` (Native Hook/Post-execution)



**2. Metadata Collection & Exfiltration Chain:**

`com.secapk.wrapper.Util.tryDo()`


$\rightarrow$ `Context.getApplicationInfo().sourceDir` (Get APK path)


$\rightarrow$ `com.secapk.wrapper.ACall.r2(packageName, apkFilePath, processName)` (Native processing/exfiltration)



## Conclusion

The application is identified as a **malicious loader/dropper** with capabilities for **information theft** and **evasive execution**. The findings are supported by the following code paths:

*   **Dynamic Loading**: `com.secapk.wrapper.ApplicationWrapper` and `com.slpresent.LMR.LMR` use `DexClassLoader` to execute code at runtime.
*   **Information Gathering**: `com.secapk.wrapper.Util.getCPUinfo`, `com.secapk.wrapper.Util.tryDo`, and `com.secapk.wrapper.Util.getField` (via reflection) are used to collect device and application metadata.
*   **Evasive Native Execution**: `com.secapk.wrapper.ACall` provides a suite of native methods used to process stolen data and proxy malicious components, specifically triggered through chains involving `com.secapk.wrapper.Util.createChildProcess` and `com.slpresent.LMR.LMR.onReceive`.