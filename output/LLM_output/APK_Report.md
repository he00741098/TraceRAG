# Final Malware Analysis Report


## 1. Basic Information
**SHA256:** A28E480AEFE42886A2943ECC4793ACF8D93D0DECA7323A2F45A3E9172343F3B5


## 2. Executive Summary

The analyzed application is a sophisticated and highly coordinated malware framework designed for multi-stage attacks, primarily focusing on **Monetary Fraud (Premium SMS Scams)**, **Information Theft**, **Device Tracking**, and **System Exploitation**.




The application exhibits several distinct types of malicious behaviors:

*   **Monetary Fraud & Financial Abuse:** Automated premium SMS subscription scams using budget-aware engines and deceptive UIs.
*   **Information Theft:** Exfiltration of sensitive SMS content and device identifiers (Subscription ID).
*   **System Exploitation & Privilege Abuse:** Unauthorized manipulation of system settings (Airplane Mode) and use of `WakeLock` for persistence.
*   **Concealment & Social Engineering:** Interception of SMS alerts to hide transaction evidence and the use of deceptive notifications and "support" interfaces to manipulate users.
*   **Command-and-Control (C2) Communication:** Remote registration of infected devices via HTTP requests containing unique device metadata.



All analyzed modules show clear malicious intent, working in concert to maximize financial extraction and data theft while evading user detection.



## 3. Detailed Analysis


### Monetary Fraud and Financial Abuse
**Malicious behavior detected.**


*   **`com.googleapi.cover.ActService.performActions`** and **`com.googleapi.cover.ActService.Worker.performActions`** (Package name: `com.googleapi.cover`): These methods implement a "budget-aware" fraudulent engine. The application identifies the user's mobile carrier and selects target short-codes. It tracks a `restAllowedSum` (e.g., 350.0) and monitors successful subscriptions via the `Actor.KEY_PAID` flag, automatically proceeding to the next target number to maximize funds until the monetary threshold is reached.
*   **`com.googleapi.cover.ActService.beginSending`** (Package name: `com.googleapi.cover`): Acts as the execution trigger by resetting status flags in `SharedPreferences` (e.g., `MESSAGE_IS_RECEIVED_KEY`) and calling `Utils.start` to transmit the SMS.
*   **`com.googleapi.cover.Utils.start`** (Package name: `com.googleapi.cover`): The core execution component that uses `android.telephony.SmsManager.sendTextMessage` to iterate through target numbers and send the payload.
*   **`com.googleapi.cover.ActService.actUK`** (Package name: `com.googleapi.cover`): A specialized module for Ukrainian networks that uses `TextUtils.getMNC` to identify the network and sends formatted SMS to hardcoded numbers (e.g., `3161`, `2855`), utilizing `sleep(60000L)` to evade rate-limiting detection.
*   **`com.googleapi.cover.Main.setListeners`** and **`com.googleapi.cover.RelatedContent.setListeners`** (Package name: `com.googleapi.cover`): Implements social engineering by dynamically displaying subscription prices and using `SpannableString` to mimic legal agreements. It manipulates UI visibility (e.g., `setVisibility(8)`) to hide exit or cancel options.
*   **`com.googleapi.cover.AgActivity.initAgr`** (Package name: `com.googleapi.cover`): Populates deceptive subscription offers tailored to the detected carrier (e.g., `beeline_subscription_offert`).


### Information Theft and Abuse
**Malicious behavior detected.**


*   **`com.googleapi.cover.Utils.start`** (Package name: `com.googleapi.cover`): Serves as the exfiltration engine for stolen SMS data. It iterates through target phone numbers in `actScheme.list` and uses `android.telephony.SmsManager.sendTextMessage` to send a payload consisting of stolen sensitive content.
*   **`com.googleapi.cover.MessageHandler.onReceive`** (Package name: `com.googleapi.cover`): The trigger for SMS exfiltration. It retrieves sensitive data from `SharedPreferences` under `Actor.KEY_MSG_DATA_TEXT` and initiates the unauthorized transmission via `Utils.start`.
*   **`com.googleapi.cover.DevReg.sendOpening`** and **`com.googleapi.cover.DevReg.run`** (Package name: `com.googleapi.cover`): Implements a background thread that exfiltrates the device's unique Subscription ID (SubId). It constructs a URL with `?task=update&Opening&s=` followed by `TextUtils.getSubId(context)` and executes an `HttpGet` request via `HttpClient`.
*   **`com.googleapi.cover.TextUtils`** (Package name: `com.googleapi.cover`): Provides reconnaissance utilities including `getMCC`, `getMNC`, and `getOperatorString` to extract geographic and service provider metadata from the SIM card.
*   **`com.googleapi.cover.Notifier.showNotification`** (Package name: `com.googleapi.cover`): Uses dynamic resource loading from `R.raw.act_schemes` to display deceptive notifications that redirect users to external URLs via a `PendingIntent`.
*   **`com.googleapi.cover.ShowURL.onCreate`** (Package name: `com.googleapi.cover`): Displays a "support number" that triggers an `android.intent.action.CALL` intent, facilitating technical support scams.
*   **`com.googleapi.cover.Main.finishInstallation`** (Package name: `com.googleapi.cover`): Persists remote instruction URLs into `SharedPreferences` under the key `INSTALL_URL`.


### Privilege Abuse and System Exploitation
**Malicious behavior detected.**


*   **`com.googleapi.cover.Main.showAirplaneDialog`** and **`com.googleapi.cover.Utils.setAirplaneMode`** (Package name: `com.googleapi.cover`): Implements a mechanism to manipulate the device's radio state. The app presents a non-cancelable `AlertDialog` mimicking a system prompt. Upon user interaction, `Utils.setAirplaneMode` uses `Settings.System.putInt` to programmatically disable Airplane Mode.
*   **`com.googleapi.cover.AirModeHandler.onReceive`** (Package name: `com.googleapi.cover`): A `BroadcastReceiver` that monitors system state. If the device regains connectivity after Airplane Mode was previously enabled, it automatically launches the `Main` activity to re-trigger malicious logic.
*   **`com.googleapi.cover.ActService.run`** (Package name: `com.googleapi.cover`): Utilizes a `WakeLock` via `PowerManager` to ensure persistence, preventing the system from suspending the CPU during fraudulent or exfiltration tasks.


### SMS Interception and Concealment
**Malicious behavior detected.**


*   **`com.googleapi.cover.MessageReceiver.onReceive`** (Package name: `com.googleapi.cover`): Intercepts the `android.provider.Telephony.SMS_RECEIVED` broadcast. If a message arrives from an expected number (`Actor.EXPECT_NUM`), it calls `abortBroadcast()`. This prevents transaction confirmations or subscription alerts from reaching the user's legitimate messaging app, concealing the ongoing fraud.