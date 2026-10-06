-- argv: app name, element index, expected role, expected name.
-- Re-reads the window and checks the element is still the same one before pressing it.
on run argv
	set appName to item 1 of argv
	set idx to (item 2 of argv) as integer
	set wantRole to item 3 of argv
	set wantName to item 4 of argv
	tell application appName to activate
	delay 0.3
	tell application "System Events"
		tell process appName
			set els to entire contents of window 1
			if idx > (count of els) then error "The window changed; read it again."
			set e to item idx of els
			set r to ""
			set nm to ""
			try
				set r to role of e
			end try
			try
				set nm to name of e
				if nm is missing value then set nm to ""
			end try
			if r is not wantRole or nm is not wantName then error "The window changed; read it again."
			try
				perform action "AXPress" of e
			on error
				click e
			end try
		end tell
	end tell
	return "pressed"
end run
