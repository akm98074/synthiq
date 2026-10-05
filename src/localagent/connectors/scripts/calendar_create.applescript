-- argv: title, startOffset, endOffset, location, calendarName ("" = first writable), notes
on run argv
	set nowD to current date
	set s to nowD + ((item 2 of argv) as number)
	set f to nowD + ((item 3 of argv) as number)
	set calName to item 5 of argv
	tell application "Calendar"
		if calName is "" then
			set cal to first calendar whose writable is true
		else
			set cal to first calendar whose name is calName
		end if
		tell cal
			set e to make new event with properties {summary:(item 1 of argv), start date:s, end date:f, location:(item 4 of argv), description:(item 6 of argv)}
		end tell
		return (name of cal) & (character id 31) & (uid of e)
	end tell
end run
