-- argv: message id
-- out: subject US sender US receivedOffset US content (first 4000 chars)
-- Looks for the id among the newest messages of each inbox only (never "whose" over a whole inbox),
-- and loads the body of that one message. (Preferred path: the .emlx file, see mailindex.py.)
property WINDOW : 300

on run argv
	set mid to (item 1 of argv) as integer
	set US to character id 31
	tell application "Mail"
		repeat with a in accounts
			set mb to missing value
			try
				set mb to mailbox "INBOX" of a
			on error
				try
					set mb to mailbox "Inbox" of a
				end try
			end try
			if mb is not missing value then
				set c to count of messages of mb
				set n to WINDOW
				if n > c then set n to c
				if c > 0 then
					if (date received of message 1 of mb) ≥ (date received of message c of mb) then
						set lst to messages 1 thru n of mb
					else
						set lst to messages (c - n + 1) thru c of mb
					end if
					repeat with m in lst
						if (id of m) is mid then
							set body to content of m
							if (length of body) > 4000 then set body to text 1 thru 4000 of body
							return (subject of m) & US & (sender of m) & US & ((date received of m) - (current date)) & US & body
						end if
					end repeat
				end if
			end if
		end repeat
	end tell
	error "That message isn't among your recent inbox messages." number -1728
end run
