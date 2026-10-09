-- argv: query ("" = any), limit, unreadOnly ("1"/"0")
-- out: id US subject US sender US receivedOffset US read US snippet RS
-- Only the newest messages of each account's inbox are looked at, and message bodies are never
-- loaded: asking Mail for "messages of inbox whose …" or "content of" every message made Mail
-- build huge object graphs it kept in memory. (Preferred path: Mail's index, see mailindex.py.)
property WINDOW : 60

on inboxes()
	set out to {}
	tell application "Mail"
		repeat with a in accounts
			try
				if enabled of a then
					set mb to missing value
					try
						set mb to mailbox "INBOX" of a
					on error
						try
							set mb to mailbox "Inbox" of a
						end try
					end try
					if mb is not missing value then set end of out to mb
				end if
			end try
		end repeat
	end tell
	return out
end inboxes

on newest(mb, n)
	tell application "Mail"
		set c to count of messages of mb
		if c is 0 then return {}
		if n > c then set n to c
		if (date received of message 1 of mb) ≥ (date received of message c of mb) then
			return messages 1 thru n of mb
		else
			return messages (c - n + 1) thru c of mb
		end if
	end tell
end newest

on run argv
	set q to item 1 of argv
	set lim to (item 2 of argv) as integer
	set unreadOnly to ((item 3 of argv) is "1")
	set RS to character id 30
	set US to character id 31
	set nowD to current date
	set out to ""
	set n to 0
	repeat with mb in my inboxes()
		repeat with m in my newest(mb, WINDOW)
			tell application "Mail"
				set isRead to read status of m
				set subj to subject of m
				set snd to sender of m
			end tell
			if (unreadOnly and isRead) or (q is not "" and not (subj contains q or snd contains q)) then
				-- skip
			else
				tell application "Mail" to set rec to ((id of m) as text) & US & subj & US & snd & US & ((date received of m) - nowD) & US & isRead & US & "" & RS
				set out to out & rec
				set n to n + 1
				if n ≥ lim * 3 then exit repeat
			end if
		end repeat
	end repeat
	return out
end run
