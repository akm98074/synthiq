-- Visible (non-background) apps; the frontmost one is marked. out: name US frontmost RS
on run argv
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "System Events"
		repeat with p in (every process whose background only is false)
			set out to out & (name of p) & US & (frontmost of p) & RS
		end repeat
	end tell
	return out
end run
