-- argv: text, handle (phone/email; empty for group chats), chatId candidates...
-- Tries each chat id first (works for groups and SMS), then the person's iMessage handle.
on run argv
	set t to item 1 of argv
	set h to item 2 of argv
	set lastErr to "no chat found"
	tell application "Messages"
		if (count of argv) > 2 then
			repeat with i from 3 to count of argv
				try
					send t to chat id (item i of argv)
					return "sent"
				on error errMsg
					set lastErr to errMsg
				end try
			end repeat
		end if
		if h is not "" then
			try
				set svc to 1st account whose service type = iMessage
				send t to participant h of svc
				return "sent"
			on error errMsg
				set lastErr to errMsg
			end try
		end if
	end tell
	error "Messages couldn't send: " & lastErr
end run
