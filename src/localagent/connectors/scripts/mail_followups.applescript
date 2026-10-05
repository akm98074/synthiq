-- argv: minDaysAgo, maxDaysAgo, limit
-- out: id US subject US sender US receivedOffset US snippet RS   (inbox messages never replied to)
on run argv
	set nowD to current date
	set newest to nowD - ((item 1 of argv) as number) * days
	set oldest to nowD - ((item 2 of argv) as number) * days
	set lim to (item 3 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "Mail"
		set msgs to (messages of inbox whose date received is greater than or equal to oldest and date received is less than or equal to newest and was replied to is false)
		set n to 0
		repeat with m in msgs
			set n to n + 1
			if n > lim then exit repeat
			set snippet to ""
			try
				set snippet to content of m
				if (length of snippet) > 300 then set snippet to text 1 thru 300 of snippet
			end try
			set out to out & (id of m) & US & (subject of m) & US & (sender of m) & US & ((date received of m) - nowD) & US & snippet & RS
		end repeat
	end tell
	return out
end run
