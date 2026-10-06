-- Names of the user's Shortcuts. out: name RS
on run argv
	set RS to character id 30
	set out to ""
	tell application "Shortcuts Events"
		repeat with s in (every shortcut)
			set out to out & (name of s) & RS
		end repeat
	end tell
	return out
end run
