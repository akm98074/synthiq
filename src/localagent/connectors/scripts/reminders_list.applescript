-- argv: listName ("" = all lists), limit
-- out: name US dueOffset ("" if none) US listName RS
on run argv
	set listName to item 1 of argv
	set lim to (item 2 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set nowD to current date
	set out to ""
	set n to 0
	tell application "Reminders"
		if listName is "" then
			set theLists to every list
		else
			set theLists to {list listName}
		end if
		repeat with L in theLists
			set lname to name of L
			repeat with r in (every reminder of L whose completed is false)
				set n to n + 1
				if n > lim then exit repeat
				set d to ""
				try
					set dd to due date of r
					if dd is not missing value then set d to ((dd - nowD) as string)
				end try
				set out to out & (name of r) & US & d & US & lname & RS
			end repeat
			if n > lim then exit repeat
		end repeat
	end tell
	return out
end run
