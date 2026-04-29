I ran across [this repository in 2026](https://github.com/Zanthox/Roll205eSheetImport), which is at least two years after [Zanthox](https://github.com/Zanthox) wrote:

> The base of this code is not mine but the work of someone 7+ years ago  that was now outdated based on roll20 changes. I've done my best with  little to no JavaScript or regex experience to get what we are able to  get out of it.

Thing is, it still pretty much works.

Pretty much.  But I had trouble following the example and seeing why it sometimes worked and sometimes didn't.  And I wanted to be able to check before I loaded up Roll20.  Hence my additions.

Some changes and additions here:

* Cleaned up the README while preserving Zanthox's voice and point of view as much as possible. 
* Human-readable formatting instructions in `human_readable_formatting_instructions.txt`
* "LLM-tuned" formatting instructions in `LLM_instructions.txt` (though YMMV)
* `preview_import.py` A python script that can help you debug and see how the importer will work (with its own `preview_import_README`)
* Separating out the example character `godfatherofassassins` and providing an `example_format`

### A note about AI usage.

* Some portios of this repository has been significantly written or altered by an AI tool with human supervision.  Usually that either means that I have written (or have) the functionality in another language, or that my understanding of that programming language (or technique) is limited.  
* In this repository, LLMs were used in these tasks:
  * Reverse-engineer how to format the input for the existing code
  * Create clear instructions for humans or other LLMs on how to best format for the existing code.
  * Clean up the formatting on the existing README so it's easier for humans to install the existing code.
  * Created `preview_import.py` a cross-platform python previewing tool to verify formatting, with super-heavy comments to explain what it's doing, why, and how it works. 
  * Maybe a commit message? 
* LLMs did not have any role in the writing of this file. 
* LLMs did not alter the existing `ImportStats v1.js`.  So if you're already using the importer, there is no need to update or change that script.  And if you have objections to any LLM usage, you now know where it has and hasn't been used. 
