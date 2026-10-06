-- argv: app name, max elements. Lists the UI elements of the app's front window
-- (needs Accessibility permission). out: windowTitle RS (index US role US name US description US value RS)*
on run argv
	set appName to item 1 of argv
	set maxN to (item 2 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "System Events"
		if not (exists process appName) then error "The app " & appName & " isn't running."
		tell process appName
			if (count of windows) = 0 then return "(no window)" & RS
			set winName to ""
			try
				set winName to name of window 1
				if winName is missing value then set winName to ""
			end try
			set els to entire contents of window 1
			set n to 0
			repeat with e in els
				set n to n + 1
				if n > maxN then exit repeat
				set r to ""
				set nm to ""
				set d to ""
				set v to ""
				try
					set r to role of e
				end try
				try
					set nm to name of e
					if nm is missing value then set nm to ""
				end try
				try
					set d to description of e
					if d is missing value then set d to ""
				end try
				try
					set v to value of e
					if v is missing value then
						set v to ""
					else
						set v to v as text
					end if
				end try
				set out to out & n & US & r & US & nm & US & d & US & v & RS
			end repeat
		end tell
	end tell
	return winName & RS & out
end run
