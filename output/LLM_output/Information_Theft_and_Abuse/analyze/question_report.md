# Malware Analysis Report


## Overall Summary

The analyzed application exhibits highly sophisticated and malicious behavior centered around **Information Theft**, **Unauthorized Data Exfiltration via SMS**, and **Social Engineering**. The application is designed to collect sensitive device identifiers (such as the SIM Subscription ID and network metadata), intercept or retrieve sensitive SMS data, and exfiltrate this information to remote attackers. Notably, the app uses a dual-channel exfiltration strategy: sending data to a Command and Control (C2) server via HTTP requests and sending stolen data to remote numbers via unauthorized SMS messages. Furthermore, the app employs deceptive UI components and notifications to facilitate social engineering attacks.



---


## Behavior Analysis Sections


### 1. Unauthorized Exfiltration of SMS Data via SMS (SMS Stealing/Smishing)
*   **Class Path**: `com.googleapi.cover.Utils.start`
*   **Analysis**: This method is the primary engine for exfiltrating stolen data. It utilizes the `SmsManager` to programmatically send text messages to a list of predefined phone numbers retrieved from a `Sch` object. The content of these messages consists of a prefix (likely a command or identifier) concatenated with a `data` string. When combined with other snippets, it is evident that this `data` string is sensitive SMS content stolen from the device.
*   **Evidence (Call Chain)**:

`com.googleapi.cover.MessageHandler.onReceive` $\rightarrow$ retrieves `smsData` from `SharedPreferences` $\rightarrow$ `com.googleapi.cover.Utils.start` $\rightarrow$ `android.telephony.SmsManager.sendTextMessage` $\rightarrow$ **Exfiltration of SMS content to remote numbers.**



### 2. Exfiltration of Device Identifiers (Information Theft)
*   **Class Path**: `com.googleapi.cover.DevReg.sendOpening` and `com.googleapi.cover.DevReg.run`
*   **Analysis**: These methods implement a background thread that performs unauthorized data collection. The code retrieves the device's unique Subscription ID (`SubId`) using `TextUtils.getSubId(context)` and appends it as a query parameter (`&s=`) to a URL constructed from a remote script path. This information is then transmitted to an attacker-controlled server via an HTTP GET request.
*   **Evidence**:

`com.googleapi.cover.DevReg.sendOpening` $\rightarrow$ `new Thread().start()` $\rightarrow$ `TextUtils.getSubId(context)` $\rightarrow$ `HttpClient.execute(HttpGet)` $\rightarrow$ **Leaking SIM/network identity to C2 server.**



### 3. Deceptive Notifications and Social Engineering
*   **Class Path**: `com.googleapi.cover.Notifier.showNotification` and `com.googleapi.cover.ShowURL.onCreate`
*   **Analysis**:
*   `com.googleapi.cover.Notifier.showNotification` dynamically constructs notifications (title, body, and action URL) by reading from raw resource files (`R.raw.act_schemes`). This allows the attacker to push arbitrary, deceptive messages to the user that redirect them to malicious websites.
*   `com.googleapi.cover.ShowURL.onCreate` implements a social engineering interface. It displays a "support number" and, upon user interaction, triggers a direct phone call (`android.intent.action.CALL`). This is a common tactic used in fraudulent technical support scams.


### 4. Systematic Information Gathering (Device/Network Metadata)
*   **Class Path**: `com.googleapi.cover.TextUtils`
*   **Analysis**: This utility class contains several methods specifically designed to harvest network and device metadata.
*   `getMCC` and `getMNC`: Extract the Mobile Country Code and Mobile Network Code.
*   `getOperatorString`: Retrieves the SIM operator information.
*   `getSubId`: Extracts a subscription identifier from internal resources.
*   `getTexts`: Parses XML resources to extract structured configuration data, which is used to orchestrate the malicious activities described above.


### 5. Remote Command and Payload Preparation
*   **Class Path**: `com.googleapi.cover.Main.finishInstallation`
*   **Analysis**: This method saves a URL retrieved from an `Actor` object into `SharedPreferences` under the key `INSTALL_URL`. This indicates the application is architected to receive and store remote URLs, which can be used to dynamically trigger the downloading of secondary payloads or the execution of remote instructions.


---


## Conclusion

The application is a malicious entity designed for comprehensive data theft and user exploitation. The core malicious activities are:


1.  **SMS Exfiltration**: Stolen SMS data is sent to remote numbers via `com.googleapi.cover.Utils.start`.


2.  **Device Tracking**: Unique Subscription IDs are leaked to a C2 server via `com.googleapi.cover.DevReg.sendOpening`.


3.  **Metadata Harvesting**: Network details (MCC, MNC, Operator) are collected via `com.googleapi.cover.TextUtils`.


4.  **Social Engineering**: Deceptive notifications and fraudulent support call triggers are implemented in `com.googleapi.cover.Notifier` and `com.googleapi.cover.ShowURL`.
