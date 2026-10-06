-- argv: shortcut name, input text (may be empty). Returns the shortcut's output as text.
on run argv
	set n to item 1 of argv
	set i to item 2 of argv
	tell application "Shortcuts Events"
		if i is "" then
			set r to run shortcut named n
		else
			set r to run shortcut named n with input i
		end if
	end tell
	try
		return r as text
	on error
		return ""
	end try
end run
