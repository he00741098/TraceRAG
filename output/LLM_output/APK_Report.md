# Final Malware Analysis Report


## 1. Basic Information
**Package Name:** com.shaahw.a8rcticiozning
**Version Code:** 8188
**Version Name:** 7.7.6x02
**SHA256:** 018f8548c055a31d98201874ebf21591e6d85cb9eee66e8c35716a9289d01f48


## 2. Executive Summary

The analysis of the application `com.shaahw.a8rcticiozning` reveals the presence of a specialized loader mechanism designed to execute hidden malicious logic via the Java Native Interface (JNI).




A total of one malicious behavior type was identified:

* **Hidden Native Payload Execution:** The application utilizes a technique to bypass static analysis by concealing its primary payload within a compiled native library (`libdecuplet.so`). The transition from the Android lifecycle to the hidden native environment is triggered immediately upon application startup through the following classes: `AnisoJstiechus.Unjudicially.Unjudicially.Unjudicially`, `AnisoJstiechus.De7E.De7E`, and `AnisoJstiechus.De7E.NativeMethods`.



No malicious behaviors were detected regarding **Monetary Fraud and Financial Abuse** or **Privilege Abuse and System Exploitation** within the analyzed code segments.



## 3. Detailed Analysis


### Information Theft and Abuse
**Malicious Behavior Detected**


**Class Path:** `AnisoJstiechus.Unjudicially.Unjudicially.Unjudicially`

The application uses this class as the entry point for executing hidden logic. The `onCreate()` method executes `System.loadLibrary("decuplet")` to load the native library `libdecuplet.so` into the process memory and immediately invokes the native method `z6gF()`. This sequence ensures the application's core functionality is transitioned to the native layer immediately upon startup to evade bytecode-based inspection.



**Class Path:** `AnisoJstiechus.De7E.De7E` and `AnisoJstiechus.De7E.NativeMethods`

These classes contain the declarations for the `z6gF()` method, which is marked with the `native` keyword. This confirms that the actual implementation of the method resides within the `libdecuplet.so` library.



**Call Chain:**

`AnisoJstiechus.Unjudicially.Unjudicially.onCreate()` $\rightarrow$ `System.loadLibrary("decuplet")` $\rightarrow$ `AnisoJstiechus.De7E.De7E.z6gF()`



### Monetary Fraud and Financial Abuse
**No Monetary Fraud and Financial Abuse Detected**

No suspicious code patterns, malicious logic, or unauthorized financial behaviors were identified in the provided code.



### Privilege Abuse and System Exploitation
**No Privilege Abuse and System Exploitation Detected**

No suspicious code patterns, malicious logic, or unauthorized system exploitation behaviors were detected in the provided content.
