# Malware Analysis Report


## Overall Summary

The analyzed application functions as a specialized loader designed to execute hidden malicious logic via the Java Native Interface (JNI). The Java layer contains no direct malicious functionality; instead, it serves as a wrapper to load a compiled native library (`libdecuplet.so`) and immediately trigger its contents. This technique is specifically employed to bypass static analysis tools by concealing the primary malicious payload within a compiled native binary.



## Behavior Analysis Sections


### Hidden Native Payload Execution
**Class Path:** `AnisoJstiechus.Unjudicially.Unjudicially.Unjudicially`



The `onCreate()` method in this class serves as the entry point for the malicious trigger. It executes `System.loadLibrary("decuplet")` to load the native library into the application's process memory and immediately invokes the `z6gF()` method. This sequence ensures that the application's core functionality is transitioned to the native layer immediately upon startup, effectively hiding the logic from bytecode-based inspection.



**Class Path:** `AnisoJstiechus.De7E.De7E`
**Class Path:** `AnisoJstiechus.De7E.NativeMethods`



These classes contain the declarations for the `z6gF()` method, marked with the `native` keyword. This confirms that the implementation of this method resides entirely within the `libdecuplet.so` library. The use of multiple class paths to declare the same native method indicates a structured approach to facilitating the transition from the Android lifecycle to the hidden native execution environment.



**Call Chain:**

`AnisoJstiechus.Unjudicially.Unjudicially.onCreate()`


$\rightarrow$ `System.loadLibrary("decuplet")` (Loads the native binary `libdecuplet.so`)


$\rightarrow$ `AnisoJstiechus.De7E.De7E.z6gF()` (Invokes the hidden native implementation)



## Conclusion

The application utilizes a JNI-based evasion technique to execute hidden logic. The malicious transition begins at `AnisoJstiechus.Unjudicially.Unjudicially.onCreate()`, which loads the native library and triggers the payload through the native method `AnisoJstiechus.De7E.De7E.z6gF()`.
