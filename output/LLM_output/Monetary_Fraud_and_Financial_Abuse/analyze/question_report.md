# Malware Analysis Report


## Overall Summary

The analyzed application is a highly sophisticated piece of malware designed for **Monetary Fraud and Financial Abuse** through automated, carrier-specific premium SMS subscription attacks. The application employs a multi-stage strategy: it identifies the user's mobile carrier and country, presents deceptive user interfaces (social engineering) to obtain "consent" for paid services, and then executes automated, budget-aware SMS transmissions to subscribe the user to premium services. To maximize financial extraction, the app monitors the success of these transactions and continues attempting further unauthorized charges until a predefined monetary threshold is reached. Furthermore, it implements advanced concealment techniques by intercepting and suppressing incoming SMS messages to prevent the user from seeing transaction alerts or confirmation messages.



---


## Behavior Analysis Sections


### 1. Automated Premium SMS Subscription (Fraudulent Charging)
* **Class Path**: `com.googleapi.cover.ActService.performActions` and `com.googleapi.cover.ActService.Worker.performActions`
* **Analysis**: These methods implement the core engine for the fraudulent subscription process. The application identifies the user's carrier (e.g., MTS, Beeline) and selects target numbers from pre-defined lists (`mfPrices` or `mtsPrices`) that are associated with specific costs. It maintains a `restAllowedSum` (set to 350.0) and iterates through subscriptions. If a subscription is successful (detected via `Actor.KEY_PAID`), it subtracts the cost from the remaining budget and proceeds to the next target number to maximize the financial extraction from the user's mobile balance.
* **Evidence (Call Chain)**:

`com.googleapi.cover.ActService.onStartCommand` $\rightarrow$ `com.googleapi.cover.ActService.Worker.run` $\rightarrow$ `com.googleapi.cover.ActService.Worker.performActions` $\rightarrow$ `com.googleapi.cover.ActService.beginSending` $\rightarrow$ `com.googleapi.cover.Utils.start` $\rightarrow$ `android.telephony.SmsManager.sendTextMessage` $\rightarrow$ **Unauthorized Premium Subscription.**



### 2. SMS Interception and Suppression (Concealment)
* **Class Path**: `com.googleapi.cover.MessageReceiver.onReceive`
* **Analysis**: To prevent the user from discovering the fraud, the application intercepts incoming SMS messages (`android.provider.Telephony.SMS_RECEIVED`). It specifically monitors for messages originating from a number stored in `Actor.EXPECT_NUM` (the service number). If a match is found, it processes the message and calls `abortBroadcast()`.
* **Evidence**: The use of `abortBroadcast()` is a critical malicious indicator; it prevents the intercepted SMS (which likely contains transaction alerts or confirmation codes) from being delivered to the user's legitimate messaging app, effectively hiding the financial theft in real-time.


### 3. Deceptive User Interface and Social Engineering
* **Class Path**: `com.googleapi.cover.Main.setListeners` and `com.googleapi.cover.RelatedContent.setListeners`
* **Analysis**: The application uses social engineering to trick users into "consenting" to charges.
* In `Main.setListeners`, it dynamically displays prices and "agreement" text based on the detected carrier. It uses `SpannableString` to underline text, mimicking a formal legal document.
* In `RelatedContent.setListeners`, it manipulates UI visibility (e.g., hiding exit buttons or agreement text via `setVisibility(8)`) to guide the user toward a "Yes" action, while presenting specific prices in Rubles (`R.string.rub`).
* **Evidence**: The combination of carrier-specific pricing and the mimicry of legal agreements is a direct tactic to facilitate fraudulent enrollment.


### 4. Targeted Network-Specific Fraud (Ukraine)
* **Class Path**: `com.googleapi.cover.ActService.actUK`
* **Analysis**: The application contains specialized logic to target mobile networks in Ukraine. It uses `TextUtils.getMNC` to identify the user's Mobile Network Code. If a target Ukrainian network is detected, it sends formatted SMS messages to hardcoded numbers (e.g., `3161`, `2855`) with a specific payload to trigger unauthorized actions or subscriptions.
* **Evidence**: The inclusion of hardcoded country-specific codes and specific MNC logic demonstrates a premeditated, targeted attack vector.


### 5. Evasion via WakeLock
* **Class Path**: `com.googleapi.cover.ActService.Worker.run`
* **Analysis**: To ensure the automated SMS loop is not interrupted by the system's power-saving features, the `Worker` thread acquires a `PowerManager.WakeLock`.
* **Evidence**: This ensures the device remains awake and the CPU remains active specifically to complete the unauthorized, backgrounded fraudulent transactions.


---


## Conclusion



The application is a highly organized piece of financial malware. The findings are summarized as follows:


1.  **Execution of Fraud**: Automated, budget-aware premium SMS subscriptions are performed via `com.googleapi.cover.ActService.performActions`.


2.  **Concealment of Theft**: The user is blinded to the theft via SMS interception and suppression in `com.googleapi.cover.MessageReceiver.onReceive`.


3.  **User Deception**: Social engineering is used to obtain "consent" through deceptive UIs in `com.googleapi.cover.Main` and `com.googleapi.cover.RelatedContent`.


4.  **Targeting**: The app uses carrier and country-specific logic (`actUK`) to optimize its fraudulent payload.
