-- argv: title, dueOffset ("" = no due date), listName ("" = default list), notes
on run argv
	set listName to item 3 of argv
	tell application "Reminders"
		if listName is "" then
			set L to default list
		else
			set L to list listName
		end if
		tell L
			set r to make new reminder with properties {name:(item 1 of argv)}
		end tell
		if (item 2 of argv) is not "" then set due date of r to (current date) + ((item 2 of argv) as number)
		if (item 4 of argv) is not "" then set body of r to (item 4 of argv)
		return name of L
	end tell
end run
