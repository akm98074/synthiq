-- argv: message id
-- out: subject US sender US receivedOffset US content (first 4000 chars)
on run argv
	set mid to (item 1 of argv) as integer
	set US to character id 31
	tell application "Mail"
		set m to first message of inbox whose id is mid
		set c to content of m
		if (length of c) > 4000 then set c to text 1 thru 4000 of c
		return (subject of m) & US & (sender of m) & US & ((date received of m) - (current date)) & US & c
	end tell
end run
