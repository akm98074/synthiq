-- argv: comma-separated recipients (no spaces), subject, body, mode ("draft" opens a compose window, "send" sends)
on run argv
	set AppleScript's text item delimiters to ","
	set recips to text items of (item 1 of argv)
	set AppleScript's text item delimiters to ""
	set mode to item 4 of argv
	tell application "Mail"
		set m to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv), visible:(mode is "draft")}
		tell m
			repeat with r in recips
				set addr to r as string
				if addr is not "" then make new to recipient at end of to recipients with properties {address:addr}
			end repeat
		end tell
		if mode is "send" then
			send m
			return "sent"
		end if
		activate
		return "draft"
	end tell
end run
