# Malware Analysis Report


## Overall Summary

The analyzed application functions as a **Dropper**, specifically designed to facilitate the side-loading and installation of a secondary application (`com.moxiu.launcher`). The application employs several deceptive and high-risk techniques, including embedding a payload within its internal assets, using social engineering via dialog boxes to trick users into installation, and implementing inter-app communication to coordinate behavior with the dropped payload.



---


## Behavior Analysis Sections


### aimoxiu.theme.carbqagp.carbqagp.installMoXiuLauncherApk
**Description:**

This method performs the core dropper functionality by extracting a hidden APK from the application's assets and preparing it for installation.



**Evidence and Technical Details:**

1.  **Extraction of Embedded APK**: The method accesses an internal asset named `/assets/MoXiuLauncher_alone.apk` using `getClass().getResourceAsStream()`. It then writes this byte stream to the application's internal storage as a file named `MoXiuLauncher_alone.apk` via `openFileOutput`.


2.  **Triggering Side-loading via Intent**: After the file is written, the method creates an `Intent` with the action `android.intent.action.VIEW` and sets the MIME type to `application/vnd.android.package-archive`. It then calls `startActivityForResult` with the URI of the extracted file, which triggers the Android system package installer to initiate the installation of the unauthorized APK.



**Call Chain:**

`aimoxiu.theme.carbqagp.carbqagp.onCreate()` $\rightarrow$ (User clicks "OK" on `AlertDialog`) $\rightarrow$ `aimoxiu.theme.carbqagp.carbqagp.installMoXiuLauncherApk()` $\rightarrow$ **System Package Installer**



### aimoxiu.theme.carbqagp.carbqagp.onCreate / onClick
**Description:**

The application utilizes social engineering tactics to deceive users into triggering the payload installation.



**Evidence and Technical Details:**

The application displays `AlertDialog` components to prompt the user to proceed with an installation. Depending on whether the target package (`com.moxiu.launcher`) is missing or outdated, it displays messages (referencing `R.string.moxiu_install_info` or `R.string.moxiu_version_info`) to encourage the user to click "OK". This click event directly invokes the `installMoXiuLauncherApk()` method.



### aimoxiu.theme.carbqagp.carbqagp.OpenMoxiuTheme / OpenThemeDetail
**Description:**

These methods demonstrate coordinated inter-app communication, suggesting the primary app and the dropped payload act as a single ecosystem.



**Evidence and Technical Details:**

Once the secondary application is detected, the primary application attempts to communicate with it using specific custom intents and component names:

*   **OpenMoxiuTheme**: Targets `com.moxiu.market.activity.ActivityMarket_main`.
*   **OpenThemeDetail**: Sends a custom intent `com.moxiu.launcher.theme.MYACTION` containing a bundle of metadata (including the original app's package name and APK path) to the secondary application.


---


## Conclusion

The application is a delivery mechanism designed to bypass standard installation processes. It hides a secondary payload within its assets, uses social engineering via `aimoxiu.theme.carbqagp.carbqagp.onCreate` to deceive users, and executes the side-loading process through `aimoxiu.theme.carbqagp.carbqagp.installMoXiuLauncherApk`. The presence of coordinated communication via `OpenMoxiuTheme` and `OpenThemeDetail` confirms that the application is part of a multi-component system designed to control the user experience or facilitate unauthorized activities.
