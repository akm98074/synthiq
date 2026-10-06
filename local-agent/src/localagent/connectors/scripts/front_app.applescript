-- The frontmost app and its front window title. out: app US title
on run argv
	set US to character id 31
	tell application "System Events"
		set p to first process whose frontmost is true
		set t to ""
		try
			set t to name of window 1 of p
			if t is missing value then set t to ""
		end try
		return (name of p) & US & t
	end tell
end run
