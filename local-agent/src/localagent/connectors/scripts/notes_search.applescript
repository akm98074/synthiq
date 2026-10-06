-- argv: query, limit
-- out: title US first 600 chars of text RS
on run argv
	set q to item 1 of argv
	set lim to (item 2 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "Notes"
		try
			set found to (every note whose name contains q or plaintext contains q)
		on error
			set found to (every note whose name contains q)
		end try
		set n to 0
		repeat with x in found
			set n to n + 1
			if n > lim then exit repeat
			set txt to plaintext of x
			if (length of txt) > 600 then set txt to text 1 thru 600 of txt
			set out to out & (name of x) & US & txt & RS
		end repeat
	end tell
	return out
end run
