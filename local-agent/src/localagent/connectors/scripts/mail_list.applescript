-- argv: query ("" = any), limit, unreadOnly ("1"/"0")
-- out: id US subject US sender US receivedOffset US read US snippet RS   (newest first, inbox of all accounts)
on run argv
	set q to item 1 of argv
	set lim to (item 2 of argv) as integer
	set unreadOnly to ((item 3 of argv) is "1")
	set RS to character id 30
	set US to character id 31
	set nowD to current date
	set out to ""
	tell application "Mail"
		if q is "" then
			if unreadOnly then
				set msgs to (messages of inbox whose read status is false)
			else
				set msgs to messages of inbox
			end if
		else
			set msgs to (messages of inbox whose subject contains q or sender contains q)
		end if
		set n to 0
		repeat with m in msgs
			if unreadOnly and (read status of m) then
				-- skip
			else
				set n to n + 1
				if n > lim then exit repeat
				set snippet to ""
				try
					set snippet to content of m
					if (length of snippet) > 300 then set snippet to text 1 thru 300 of snippet
				end try
				set out to out & (id of m) & US & (subject of m) & US & (sender of m) & US & ((date received of m) - nowD) & US & (read status of m) & US & snippet & RS
			end if
		end repeat
	end tell
	return out
end run
