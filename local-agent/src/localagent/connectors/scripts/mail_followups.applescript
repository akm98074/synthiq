-- argv: minDaysAgo, maxDaysAgo, limit
-- out: id US subject US sender US receivedOffset US snippet RS   (inbox messages never replied to)
-- Bounded like mail_list: newest messages of each inbox only, no message bodies.
property WINDOW : 120

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
	set nowD to current date
	set newestD to nowD - ((item 1 of argv) as number) * days
	set oldestD to nowD - ((item 2 of argv) as number) * days
	set lim to (item 3 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set out to ""
	set n to 0
	repeat with mb in my inboxes()
		repeat with m in my newest(mb, WINDOW)
			tell application "Mail"
				set d to date received of m
				if d ≥ oldestD and d ≤ newestD and not (was replied to of m) then
					set out to out & ((id of m) as text) & US & (subject of m) & US & (sender of m) & US & (d - nowD) & US & "" & RS
					set n to n + 1
				end if
			end tell
			if n ≥ lim then exit repeat
		end repeat
	end repeat
	return out
end run
