# Malware Analysis Report


## Overall Summary

The analyzed application is a highly sophisticated malware framework designed for **Monetary Fraud and Financial Abuse**, specifically targeting users through **Automated Premium SMS Subscription Scams**. The application employs a multi-stage attack pattern: it uses social engineering to trick users into "consenting" to services via deceptive UIs, automates the sending of premium-rate SMS messages to maximize financial extraction within a defined budget, and implements advanced concealment techniques by intercepting and suppressing incoming SMS messages to hide transaction alerts from the victim.



---


## Behavior Analysis Sections


### Automated Premium SMS Subscription (Fraudulent Charging)
*   **`com.googleapi.cover.ActService.performActions`** and **`com.googleapi.cover.ActService.Worker.performActions`**

These methods implement a "budget-aware" fraudulent engine. The application identifies the user's mobile carrier (e.g., Beeline, MTS) and selects target short-codes or phone numbers. It maintains a `restAllowedSum` (e.g., 350.0) and tracks the "price" of each successful subscription via `mfPrices` or `mtsPrices`. If a subscription is successful (detected via the `Actor.KEY_PAID` flag), the code automatically proceeds to the next number in the sequence to continue extracting funds until the monetary threshold is reached.



*   **`com.googleapi.cover.ActService.beginSending`**

This method acts as the execution trigger. It prepares the environment by resetting status flags in `SharedPreferences` (e.g., `MESSAGE_IS_RECEIVED_KEY` and `KEY_PAID`) and then calls `Utils.start` to physically transmit the SMS message to the target number.



*   **`com.googleapi.cover.Utils.start`**

The core execution component that uses `android.telephony.SmsManager.sendTextMessage` to iterate through a list of target numbers and send the payload. This is the primary mechanism for triggering unauthorized premium charges.



*   **`com.googleapi.cover.ActService.actUK`**

A specialized module targeting Ukrainian mobile networks. It uses `TextUtils.getMNC` to identify the user's network and sends formatted SMS messages to hardcoded numbers (e.g., `3161`, `2855`) to trigger unauthorized services, including a `sleep(60000L)` delay to evade rate-limiting detection.



**Malicious Call Chain:**

`com.googleapi.cover.ActService.onStartCommand` $\rightarrow$ `com.googleapi.cover.ActService.Worker.run` $\rightarrow$ `com.googleapi.cover.ActService.Worker.performActions` $\rightarrow$ `com.googleapi.cover.ActService.beginSending` $\rightarrow$ `com.googleapi.cover.Utils.start` $\rightarrow$ `android.telephony.SmsManager.sendTextMessage`



---


### SMS Interception and Concealment
*   **`com.googleapi.cover.MessageReceiver.onReceive`**

This component is critical for the success of the fraud by hiding evidence. It intercepts the `android.provider.Telephony.SMS_RECEIVED` broadcast. When a message arrives from an expected number (`Actor.EXPECT_NUM`), it processes the body and then calls **`abortBroadcast()`**. This prevents the intercepted SMS (which often contains transaction confirmations or subscription alerts) from being delivered to the user's legitimate messaging app, ensuring the victim remains unaware of the ongoing charges.



---


### Deceptive User Interface and Social Engineering
*   **`com.googleapi.cover.Main.setListeners`** and **`com.googleapi.cover.RelatedContent.setListeners`**

These methods implement social engineering tactics. The app dynamically displays subscription prices (e.g., in Rubles) and uses `SpannableString` to underline text, mimicking a formal legal agreement. It manipulates UI visibility (e.g., `setVisibility(8)`) to hide "exit" or "cancel" options, guiding the user toward clicking a "Yes" button to trigger the subscription.



*   **`com.googleapi.cover.AgActivity.initAgr`**

Used to populate deceptive subscription offers tailored to the detected carrier (e.g., "beeline_subscription_offert"), presenting them as legitimate service options.



*   **`com.googleapi.cover.ShowURL.onCreate`** and **`com.googleapi.cover.Notifier.showNotification`**

These components manage the post-fraud phase. They use notifications and "Thank you" screens to redirect users to external URLs, potentially to provide a fake landing page or to complete the fraudulent cycle.



---


## Conclusion



The application's functionality is centered around a coordinated effort to commit financial fraud:


1.  **Deception**: Using `com.googleapi.cover.Main` and `com.googleapi.cover.RelatedContent` to trick users into "accepting" paid services.


2.  **Execution**: Using `com.googleapi.cover.ActService` and `com.googleapi.cover.Utils` to automate high-frequency, budget-limited premium SMS subscriptions.


3.  **Concealment**: Using `com.googleapi.cover.MessageReceiver` to suppress incoming SMS alerts, preventing the user from noticing the unauthorized activity.
