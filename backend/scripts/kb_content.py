"""Help articles for the three demo tenants.

Fictitious companies, deliberately different from each other (different VPN client, different policies),
so that "which company's answer did you get?" is visible in a demo and testable in the evals.
"""

ARTICLES: dict[str, list[tuple[str, str]]] = {
    "acme": [
        (
            "VPN troubleshooting",
            "Acme uses the AcmeConnect VPN client. If it disconnects every few minutes, update AcmeConnect to "
            "version 5 from the Software Center and turn off power saving on your wifi adapter (Device Manager, "
            "Network adapters, Power Management).\n\n"
            "If you cannot connect at all from home, check that your laptop clock is correct, because the "
            "certificate only works within a few minutes of real time. Then sign out of AcmeConnect and sign in "
            "again so it fetches a fresh certificate. The gateway address is vpn.acme.test.\n\n"
            "If it still fails, open AcmeConnect, choose Help, Send diagnostics, and attach the log to a ticket.",
        ),
        (
            "Resetting your password",
            "Acme passwords must be at least 14 characters and are never reused for 12 months. You can reset "
            "your own password at selfservice.acme.test using your phone for verification.\n\n"
            "After 5 wrong attempts the account locks for 30 minutes. If you are locked out and cannot use "
            "self-service, ask the helpdesk assistant for a reset: a support agent must approve it before a "
            "one-time reset link is sent to your work email. Support will never ask you for your password.",
        ),
        (
            "Email on your phone",
            "To read work email on a phone, install the Company Portal app (App Store or Google Play), sign in "
            "with your Acme account and accept the device policy. Your email, calendar and contacts appear "
            "within a few minutes.\n\n"
            "The device must have a screen lock of at least 6 digits. If you replace your phone, remove the old "
            "one under Devices in the Company Portal so it stops syncing.",
        ),
        (
            "CRM is slow or not loading",
            "Our CRM is Northwind CRM. It is slowest on Mondays between 8:00 and 9:00 when the weekly reports "
            "run. If pages spin forever, clear the site data for crm.acme.test and reload, or open the lite view "
            "at crm.acme.test/lite which skips the dashboards.\n\n"
            "If the CRM status in the helpdesk shows degraded, the issue is known and engineering is working on "
            "it; you do not need to open another ticket unless you are blocked from a customer meeting.",
        ),
        (
            "Requesting access to systems",
            "Access to a system needs a business reason and your manager's agreement. Tell the helpdesk "
            "assistant which system you need and why; it submits the request and a support agent approves or "
            "rejects it. Finance systems also need a second approval from the Finance lead.\n\n"
            "Access is reviewed every quarter and removed when it is no longer used.",
        ),
        (
            "Wi-Fi at the office",
            "Employees connect to the ACME-Corp network using their work account; the first time, install the "
            "Acme root certificate when prompted. Visitors use ACME-Guest, which needs the daily code from "
            "reception and only reaches the internet, never internal systems.\n\n"
            "If ACME-Corp keeps asking for credentials, forget the network and join it again.",
        ),
        (
            "Laptop problems",
            "If your laptop will not turn on, hold the power button for 15 seconds, plug in the charger and wait "
            "5 minutes before trying again. A black screen with the fan running usually means the battery "
            "needs a reset.\n\n"
            "Hardware swaps are handled at the IT desk on the third floor, Monday to Friday 9:00 to 17:00. "
            "Bring the laptop and your badge. Loaner laptops are available for up to 3 days.",
        ),
    ],
    "globex": [
        (
            "VPN troubleshooting",
            "Globex uses GlobexSecure with a hardware security token. If the VPN refuses to enrol your token, "
            "unplug it, wait ten seconds and plug it into a different USB port, then start enrolment again "
            "from the GlobexSecure tray icon.\n\n"
            "Frequent disconnects are usually the router: reboot it and avoid public wifi without the "
            "always-on option enabled. Connection problems from abroad need the travel profile, which support "
            "can enable for you.",
        ),
        (
            "Email outage runbook",
            "When the Globex email system is down, urgent messages go through the backup webmail at "
            "mail-backup.globex.test using your normal login. It only handles sending and receiving, with no "
            "calendar.\n\n"
            "Do not resend the same message repeatedly: queued mail is delivered automatically when service "
            "returns. Customer-facing teams should also post in the Operations chat channel so colleagues know.",
        ),
        (
            "Payroll portal",
            "Payslips and tax forms are in the Payroll Portal. Employees sign in with Globex single sign-on and "
            "can download the last 24 months of payslips as PDF. Access to the portal for managers needs the "
            "Payroll role, granted by HR.\n\n"
            "Payslips are published on the 25th of each month. Questions about amounts go to HR, not IT.",
        ),
        (
            "Resetting your password",
            "Globex passwords need 12 characters and a symbol. Password resets are never done automatically: "
            "the helpdesk assistant requests the reset and a support agent has to approve it after checking "
            "your identity. This usually takes under an hour during office hours.\n\n"
            "Once approved, a one-time link is sent to your work email and expires after 30 minutes.",
        ),
        (
            "Lost or broken security token",
            "If you lose your GlobexSecure token or it stops working, tell the helpdesk right away so the old "
            "token can be disabled. A replacement is issued at the security desk with photo ID and takes about "
            "ten minutes.\n\n"
            "While you wait you can use the one-time codes that were printed when you enrolled, if you kept them.",
        ),
        (
            "Printing at Globex",
            "Printers use follow-me printing: send the job to the Globex-Print queue, then badge in at any "
            "printer to release it. Jobs that are not released within 24 hours are deleted.\n\n"
            "If the printer does not recognise your badge, ask support to re-register it. Colour printing needs "
            "your manager's approval.",
        ),
    ],
    "initech": [
        (
            "TPS reports portal",
            "Every TPS report must include the new cover sheet before submission, or the TPS Reports Portal "
            "will reject it with a formatting error. Download the cover sheet template from the portal's "
            "Documents tab and attach it as the first page.\n\n"
            "Reports are due by Friday 15:00. If the portal rejects a correct report, clear your browser cache "
            "and submit again, and tell your manager.",
        ),
        (
            "VPN troubleshooting",
            "Initech staff connect with the Initrode VPN client. If the connection fails, restart the "
            "Initrode service from the system tray and sign in again with your Initech username, without the "
            "domain prefix.\n\n"
            "Contractors receive a separate profile; ask your sponsor to request it.",
        ),
        (
            "Intranet is slow",
            "The Initech intranet is sometimes degraded during the monthly content publishing window, the "
            "first Tuesday of each month. Pages load slowly or time out. Use the printable policy pack on the "
            "shared drive in the meantime.\n\n"
            "If the intranet is slow outside that window, report it with the page address and the time.",
        ),
        (
            "Installing new software",
            "Standard software is installed from the Software Center without a ticket. Anything else needs a "
            "software request with the vendor name, the licence cost and your manager's approval; security "
            "reviews take up to 5 business days.\n\n"
            "Do not install software from personal downloads on a company laptop.",
        ),
        (
            "Meeting room displays",
            "To present in a meeting room, connect your laptop to the wireless display by choosing the room "
            "name in your display settings and entering the code shown on the screen. If the screen stays "
            "black, press the input button on the remote until the wireless source is selected.\n\n"
            "Rooms with a wall cable support USB-C and HDMI; adapters are in the drawer under the screen.",
        ),
    ],
}
