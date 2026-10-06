-- argv: name query, limit
-- out: name US emails (comma) US phones (comma) RS
on run argv
	set q to item 1 of argv
	set lim to (item 2 of argv) as integer
	set RS to character id 30
	set US to character id 31
	set out to ""
	tell application "Contacts"
		set ps to (every person whose name contains q)
		set n to 0
		repeat with p in ps
			set n to n + 1
			if n > lim then exit repeat
			set em to ""
			repeat with e in (emails of p)
				set em to em & (value of e) & ","
			end repeat
			set ph to ""
			repeat with t in (phones of p)
				set ph to ph & (value of t) & ","
			end repeat
			set out to out & (name of p) & US & em & US & ph & RS
		end repeat
	end tell
	return out
end run
