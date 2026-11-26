"""S-0 submission candidates. Meta approval/category is not guaranteed.

Submit these exact bodies with language en and sample values for each slot.
"""
TEMPLATES = {
    "reminder_v1": ("Reminder: {{1}} is due at {{2}}.", 2),
    "meeting_reminder_v1": ("Meeting reminder: {{1}} at {{2}}.", 2),
    "deadline_reminder_v1": ("Deadline reminder: {{1}} is due at {{2}}.", 2),
    "commitment_due_v1": ("Commitment reminder: {{1}} is due at {{2}}.", 2),
    "already_sent_knock_v1": ("A reminder for {{1}} was already sent at {{2}}.", 2),
    "mirror_stale_v1": ("Your reminder list has not been refreshed since {{1}}. Reminders are paused.", 1),
}
