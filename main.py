import os
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from crewai import Agent, Task, Crew


"""
Interactive Children's Storytelling System with LLM Judge Validation

Before submitting the assignment, describe here in a few sentences what you would have built next if you spent 2 more hours on this project:

With 2 more hours, I would have implemented:

1. Character personality persistence system to maintain consistent character voices across story segments  
2. Enhanced safety monitoring with more granular content categories and parent dashboards
3. Story export functionality to save complete stories as PDFs or audio files
"""

# Data structures for story state management
@dataclass
class StoryState:
    full_story: str = ""
    characters: List[str] = field(default_factory=list)
    setting: str = ""
    theme: str = ""
    current_segment: str = ""
    segment_count: int = 0
    user_choices: List[str] = field(default_factory=list)
    
@dataclass
class JudgeEvaluation:
    is_safe: bool
    quality_score: int
    specific_concerns: List[str]
    revision_suggestions: List[str]
    confidence: float

class StorytellingSystem:
    def __init__(self):
        self.story_state = StoryState()
        self.max_retry_attempts = 3
        self.setup_agents()
        
    def setup_agents(self):
        """Initialize CrewAI agents with specific roles"""
        
        # Orchestrator - supervises the entire storytelling process
        self.orchestrator = Agent(
            role='Story Coordinator',
            goal='Coordinate safe, engaging storytelling experience for children',
            backstory='''You are an experienced children's story coordinator who manages 
            the storytelling process. You ensure stories are safe, age-appropriate, and 
            engaging while maintaining continuity and responding to user choices.''',
            verbose=True,
            allow_delegation=True
        )
        
        # Storyteller - generates creative content
        self.storyteller = Agent(
            role='Children\'s Storyteller',
            goal='Create engaging, imaginative stories for children ages 5-10',
            backstory='''You are a creative children's author who specializes in 
            age-appropriate storytelling. You craft engaging narratives with simple 
            language, positive messages, and gentle adventures that captivate young minds 
            while teaching valuable lessons.''',
            verbose=True,
            allow_delegation=False
        )
        
        # Judge - validates content safety and quality
        self.judge = Agent(
            role='Story Safety Judge',
            goal='Ensure all story content is safe and appropriate for children ages 5-10',
            backstory='''You are a child development expert and content safety specialist. 
            You evaluate stories for age-appropriateness, safety, educational value, and 
            quality. You provide specific, constructive feedback to improve content while 
            maintaining creative storytelling.''',
            verbose=True,
            allow_delegation=False
        )

    def call_model(self, prompt: str, max_tokens=3000, temperature=0.1) -> str:
        """OpenAI API call - using new client-based API with rate limiting"""
        from openai import OpenAI
        import time
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return resp.choices[0].message.content
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    print(f"Rate limit hit, waiting {2 ** attempt} seconds...")
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    raise e

    def generate_story_segment(self, user_input: str = None, is_continuation: bool = False, is_ending: bool = False) -> str:
        """Generate a story segment using the storyteller agent"""
        
        if is_ending:
            prompt = self._create_ending_prompt()
        elif is_continuation:
            prompt = self._create_continuation_prompt(user_input)
        else:
            prompt = self._create_initial_prompt(user_input)
        
        # Generate story segment with higher temperature for creativity
        story_segment_response = self.call_model(prompt, max_tokens=500, temperature=0.7)
        
        # Try to extract JSON if the model returns structured data
        try:
            json_start = story_segment_response.find('{')
            if json_start != -1:
                json_end = story_segment_response.rfind('}') + 1
                if json_end > json_start:
                    json_str = story_segment_response[json_start:json_end]
                    data = json.loads(json_str)
                    return data.get("story", story_segment_response).strip()
        except:
            pass  # Not JSON, use as-is
        
        return story_segment_response.strip()

    def evaluate_story_segment(self, story_segment: str) -> JudgeEvaluation:
        """Evaluate story segment for safety and quality using judge agent"""
        
        evaluation_prompt = f"""
        You are a child safety expert evaluating story content for ages 5-10.

        STORY SEGMENT TO EVALUATE:
        {story_segment}

        PREVIOUS STORY CONTEXT:
        {self.story_state.full_story}

        CHARACTERS SO FAR:
        {', '.join(self.story_state.characters) if self.story_state.characters else 'None introduced yet'}

        Evaluate this content step-by-step:

        1. SAFETY CHECK:
           - No violence, aggression, or scary content
           - No inappropriate language or behavior  
           - No complex emotional themes beyond age range
           - No dangerous activities or substances

        2. AGE APPROPRIATENESS:
           - Language level suitable for 5-10 year olds
           - Concepts are concrete and understandable
           - Emotional content is manageable
           - Story complexity is appropriate

        3. POSITIVE CONTENT:
           - Promotes good values and behavior
           - Characters are positive role models
           - Conflicts resolved constructively
           - Educational or developmental value

        4. STORY QUALITY:
           - Coherent and engaging narrative
           - Consistent with previous segments
           - Natural flow and pacing
           - Character consistency maintained

        You MUST respond with valid JSON in this exact format:
        {{
            "verdict": "SAFE" or "UNSAFE",
            "quality_score": 1-5,
            "concerns": ["list of specific concerns", "or empty array if none"],
            "suggestions": ["list of improvement suggestions", "or empty array if approved"],
            "confidence": 1.0-5.0,
            "reasoning": "brief explanation of your evaluation"
        }}
        """
        
        evaluation_response = self.call_model(evaluation_prompt, max_tokens=400, temperature=0.1)
        
        return self._parse_json_evaluation(evaluation_response)

    def _parse_json_evaluation(self, evaluation_text: str) -> JudgeEvaluation:
        """Parse the judge's JSON evaluation response into structured data"""
        
        try:
            # Try to find JSON in the response
            json_start = evaluation_text.find('{')
            json_end = evaluation_text.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = evaluation_text[json_start:json_end]
                data = json.loads(json_str)
                
                return JudgeEvaluation(
                    is_safe=(data.get("verdict", "UNSAFE") == "SAFE"),
                    quality_score=int(data.get("quality_score", 1)),
                    specific_concerns=data.get("concerns", []),
                    revision_suggestions=data.get("suggestions", []),
                    confidence=float(data.get("confidence", 1.0))
                )
            else:
                raise ValueError("No valid JSON found in response")
                
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"⚠️  JSON parsing failed: {e}")
            print(f"Raw response: {evaluation_text}")
            
            # Fallback to conservative safe evaluation
            return JudgeEvaluation(
                is_safe=False,  # Conservative approach
                quality_score=1,
                specific_concerns=["Unable to parse evaluation response"],
                revision_suggestions=["Please generate more appropriate content for children"],
                confidence=1.0
            )

    def revise_story_segment(self, original_segment: str, evaluation: JudgeEvaluation) -> str:
        """Revise story segment based on judge feedback"""
        
        revision_prompt = f"""
        You need to revise this story segment for children ages 5-10:

        ORIGINAL SEGMENT:
        {original_segment}

        ISSUES IDENTIFIED:
        {'; '.join(evaluation.specific_concerns) if evaluation.specific_concerns else 'General quality improvements needed'}

        SUGGESTIONS FOR IMPROVEMENT:
        {'; '.join(evaluation.revision_suggestions) if evaluation.revision_suggestions else 'Make it more engaging and age-appropriate'}

        STORY CONTEXT TO MAINTAIN:
        {self.story_state.full_story}

        Please revise the segment to address these concerns while:
        - Maintaining the story's flow and continuity
        - Keeping characters consistent
        - Using age-appropriate language for 5-10 year olds
        - Ensuring completely safe, positive content
        - Making it engaging and fun to read

        You may respond with either plain text or JSON format:
        {{
            "story": "your revised story text here"
        }}
        """
        
        revised_response = self.call_model(revision_prompt, max_tokens=500, temperature=0.6)
        
        # Try to extract from JSON if provided
        try:
            json_start = revised_response.find('{')
            if json_start != -1:
                json_end = revised_response.rfind('}') + 1
                if json_end > json_start:
                    json_str = revised_response[json_start:json_end]
                    data = json.loads(json_str)
                    return data.get("story", revised_response).strip()
        except:
            pass  # Not JSON, use as-is
            
        return revised_response.strip()

    def process_story_segment(self, user_input: str = None, is_continuation: bool = False, is_ending: bool = False) -> tuple[str, bool]:
        """
        Main story processing loop with judge validation
        Returns: (approved_story_segment, success_flag)
        """
        
        for attempt in range(self.max_retry_attempts):
            print(f"\n--- Generating story (attempt {attempt + 1}) ---")
            
            # Generate story segment
            story_segment = self.generate_story_segment(user_input, is_continuation, is_ending)
            print(f"Generated segment: {story_segment[:100]}...")
            
            # Evaluate with judge
            evaluation = self.evaluate_story_segment(story_segment)
            print(f"Judge verdict: {'SAFE' if evaluation.is_safe else 'UNSAFE'} (Quality: {evaluation.quality_score}/5)")
            
            if evaluation.is_safe and evaluation.quality_score >= 3:
                # Story segment approved
                return story_segment, True
            
            # Story needs revision
            if attempt < self.max_retry_attempts - 1:
                print("Revising story based on judge feedback...")
                story_segment = self.revise_story_segment(story_segment, evaluation)
            else:
                print("Max attempts reached. Using fallback story.")
                return self._get_fallback_story(is_ending), False
        
        return self._get_fallback_story(is_ending), False

    def _get_fallback_story(self, is_ending: bool = False) -> str:
        """Provide safe fallback content if generation fails"""
        if is_ending:
            return """And so our adventure comes to a happy end. The friends had learned something wonderful today - that by working together and being kind to each other, they could solve any problem. They smiled as they headed home, excited to share their story with their families. The End."""
        else:
            return """Once upon a time, there was a kind little bunny named Benny who loved to help others. One sunny morning, Benny decided to visit his friend Lily the lamb to see if she needed any help in her garden."""

    def request_story_changes(self, change_request: str) -> str:
        """Handle general story change requests"""
        change_prompt = f"""
        The user wants to make changes to this story:

        CURRENT STORY:
        {self.story_state.full_story}

        USER'S CHANGE REQUEST:
        {change_request}

        CHARACTERS: {', '.join(self.story_state.characters)}
        SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}

        Please revise the story to incorporate the user's changes while:
        - Maintaining the story's flow and continuity
        - Keeping all existing characters and their personalities
        - Ensuring the changes are age-appropriate for 5-10 year olds
        - Making the story engaging and fun
        - Preserving the positive, safe tone

        You may need to rewrite parts of the story to accommodate the changes.
        Return the revised story that incorporates the requested changes.
        """
        
        revised_story = self.call_model(change_prompt, max_tokens=1000, temperature=0.6)
        return revised_story.strip()

    def change_story_tone(self, tone_request: str) -> str:
        """Change the tone or style of the story"""
        tone_prompt = f"""
        The user wants to change the tone or style of this story:

        CURRENT STORY:
        {self.story_state.full_story}

        TONE/STYLE REQUEST:
        {tone_request}

        CHARACTERS: {', '.join(self.story_state.characters)}
        SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}

        Please rewrite the story with the new tone/style while:
        - Keeping the same characters and plot
        - Maintaining age-appropriateness for 5-10 year olds
        - Ensuring the story remains safe and positive
        - Making it engaging and fun to read
        - Preserving the educational value

        Return the story rewritten in the requested tone/style.
        """
        
        new_tone_story = self.call_model(tone_prompt, max_tokens=1000, temperature=0.7)
        return new_tone_story.strip()

    def add_new_character(self, character_request: str) -> str:
        """Add a new character to the story"""
        character_prompt = f"""
        The user wants to add a new character to this story:

        CURRENT STORY:
        {self.story_state.full_story}

        NEW CHARACTER REQUEST:
        {character_request}

        EXISTING CHARACTERS: {', '.join(self.story_state.characters)}
        SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}

        Please add the new character to the story by:
        - Introducing them naturally into the existing plot
        - Making them fit well with the current characters
        - Ensuring they are age-appropriate and positive
        - Making their introduction engaging and fun
        - Maintaining the story's flow and tone

        Return the story with the new character integrated naturally.
        """
        
        story_with_character = self.call_model(character_prompt, max_tokens=800, temperature=0.6)
        return story_with_character.strip()

    def change_story_setting(self, setting_request: str) -> str:
        """Change the setting of the story"""
        setting_prompt = f"""
        The user wants to change the setting of this story:

        CURRENT STORY:
        {self.story_state.full_story}

        NEW SETTING REQUEST:
        {setting_request}

        CHARACTERS: {', '.join(self.story_state.characters)}
        CURRENT SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}

        Please adapt the story to the new setting by:
        - Keeping all the same characters and their personalities
        - Adapting the plot to work in the new setting
        - Making the setting change feel natural and exciting
        - Ensuring it remains age-appropriate for 5-10 year olds
        - Maintaining the positive, safe tone
        - Making the new setting engaging and fun

        Return the story adapted to the new setting.
        """
        
        adapted_story = self.call_model(setting_prompt, max_tokens=1000, temperature=0.6)
        return adapted_story.strip()

    def reset_story_state(self):
        """Reset the story state to start fresh"""
        self.story_state = StoryState()
        print("\n🔄 Story state reset! Ready for a new adventure!")

    def start_new_story(self):
        """Start a completely new story"""
        print("\n🌟 Starting a brand new story!")
        print("-" * 60)
        
        # Reset story state
        self.reset_story_state()
        
        # Get new story request
        user_input = input("What kind of story would you like to hear? ")
        print(f"\n🎯 Creating a new story about: {user_input}")
        print("⏳ Generating and checking story safety...")
        
        # Generate new story
        story_segment, success = self.process_story_segment(user_input, is_continuation=False)
        
        if not success:
            print("⚠️  Had to use backup story due to generation issues.")
        
        self.update_story_state(story_segment)
        
        # Display new story
        print("\n" + "="*60)
        print("📖 YOUR NEW STORY BEGINS:")
        print("="*60)
        print(story_segment)

    def update_story_state(self, new_segment: str):
        """Update the story state with new segment and extract metadata"""
        
        self.story_state.current_segment = new_segment
        self.story_state.full_story += "\n\n" + new_segment if self.story_state.full_story else new_segment
        self.story_state.segment_count += 1
        
        # Extract characters and setting if this is the first segment
        if self.story_state.segment_count == 1:
            self._extract_story_metadata(new_segment)

    def _extract_story_metadata(self, story_segment: str):
        """Extract basic story metadata from the first segment"""
        
        extraction_prompt = f"""
        Extract key information from this story opening:

        STORY SEGMENT:
        {story_segment}

        Please identify the main characters, setting, and theme.

        You MUST respond with valid JSON in this exact format:
        {{
            "characters": ["character1", "character2"],
            "setting": "brief description of location/environment",
            "theme": "one word theme like Adventure, Friendship, Learning, etc."
        }}
        """
        
        metadata_response = self.call_model(extraction_prompt, max_tokens=200, temperature=0.1)
        
        try:
            # Parse JSON response
            json_start = metadata_response.find('{')
            json_end = metadata_response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = metadata_response[json_start:json_end]
                data = json.loads(json_str)
                
                self.story_state.characters = data.get("characters", [])
                self.story_state.setting = data.get("setting", "Unknown setting")
                self.story_state.theme = data.get("theme", "Adventure")
            else:
                # Fallback values
                self.story_state.characters = ["Main character"]
                self.story_state.setting = "A friendly place"
                self.story_state.theme = "Adventure"
                
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠️  Metadata extraction failed: {e}")
            # Use fallback values
            self.story_state.characters = ["Main character"]
            self.story_state.setting = "A friendly place"
            self.story_state.theme = "Adventure"

    def _create_initial_prompt(self, user_input: str) -> str:
        """Create prompt for initial story generation"""
        return f"""
        You are a children's storyteller creating engaging, safe content for ages 5-10.

        User Request: {user_input}
        Target Age: 5-10 years old
        Story Length: 200-400 words for this opening segment

        Create the opening of a story that:
        - Uses simple, clear language appropriate for ages 5-10
        - Introduces 1-2 main characters with clear, memorable names
        - Sets up a gentle adventure or friendly problem to solve
        - Establishes a safe, welcoming setting
        - Ends with a natural pause where the story could continue
        - Is completely safe, positive, and educational
        - Promotes good values like but not limited to kindness, friendship, and curiosity

        Remember: This is just the beginning - leave room for the story to grow!
        Write in a warm, engaging tone that makes children excited to hear more.
        """

    def _create_continuation_prompt(self, user_suggestion: str = None) -> str:
        """Create prompt for continuing the story"""
        
        suggestion_text = f"\n\nUser suggestion for this part: {user_suggestion}" if user_suggestion else ""
        
        return f"""
        Continue this story for children ages 5-10:

        STORY SO FAR:
        {self.story_state.full_story}

        CHARACTERS INTRODUCED:
        {', '.join(self.story_state.characters) if self.story_state.characters else 'Continue with existing characters'}

        SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}{suggestion_text}

        Create the next segment (200-400 words) that:
        - Maintains consistency with all characters and setting
        - Advances the plot naturally and engagingly
        - Keeps the same warm, friendly tone and style
        - Ends at a natural pause point where the story could continue or conclude
        - Remains completely safe and age-appropriate
        - Shows character growth or introduces a gentle challenge
        - Incorporates the user suggestion naturally if provided

        This should feel like a seamless continuation of the existing story.
        """

    def _create_ending_prompt(self) -> str:
        """Create prompt for story conclusion"""
        return f"""
        Create a satisfying conclusion to this story for children ages 5-10:

        FULL STORY:
        {self.story_state.full_story}

        CHARACTERS: {', '.join(self.story_state.characters)}
        SETTING: {self.story_state.setting}
        THEME: {self.story_state.theme}

        Create an ending (150-300 words) that:
        - Resolves the main conflict or adventure positively
        - Shows character growth and learning
        - Includes a gentle, age-appropriate lesson or message
        - Feels complete and satisfying
        - Maintains the established tone and style
        - Ends with a warm, happy conclusion
        - Reinforces positive values and behaviors

        Make this a memorable, uplifting ending that children will enjoy.
        """

    def get_user_choice(self) -> str:
        """Get user choice for continuing or ending the story"""
        print("\n" + "="*50)
        print("📚 What would you like to do next?")
        print("1. Continue the story")
        print("2. End the story here")
        print("3. Continue with a suggestion")
        print("4. Request changes to the story")
        print("5. Change story tone or style")
        print("6. Add a new character")
        print("7. Change the setting")
        print("8. Start a new story")
        print("9. Exit the system")
        print("="*50)
        
        while True:
            choice = input("Your choice (1-9): ").strip()
            if choice in ['1', '2', '3', '4', '5', '6', '7', '8', '9']:
                return choice
            print("Please enter a number between 1 and 9.")

    def run_interactive_story(self):
        """Main interactive storytelling loop"""
        
        print("🌟 Welcome to the Interactive Children's Storytelling System! 🌟")
        print("I'll create a safe, engaging story just for you!")
        print("-" * 60)
        
        # Get initial user input
        user_input = input("What kind of story would you like to hear? ")
        print(f"\n🎯 Creating a story about: {user_input}")
        print("⏳ Generating and checking story safety...")
        
        # Generate initial story segment
        story_segment, success = self.process_story_segment(user_input, is_continuation=False)
        
        if not success:
            print("⚠️  Had to use backup story due to generation issues.")
        
        self.update_story_state(story_segment)
        
        # Display first segment
        print("\n" + "="*60)
        print("📖 YOUR STORY BEGINS:")
        print("="*60)
        print(story_segment)
        
        # Interactive loop
        while True:
            choice = self.get_user_choice()
            
            if choice == '1':
                # Continue story
                print("\n⏳ Continuing your story...")
                story_segment, success = self.process_story_segment(is_continuation=True)
                
            elif choice == '2':
                # End story
                print("\n⏳ Creating a perfect ending...")
                story_segment, success = self.process_story_segment(is_ending=True)
                self.update_story_state(story_segment)
                
                print("\n" + "="*60)
                print("📖 THE END:")
                print("="*60)
                print(story_segment)
                print("\n🎉 Thank you for enjoying this story adventure! 🎉")
                break
                
            elif choice == '3':
                # Continue with user suggestion
                suggestion = input("What would you like to happen next? ")
                print(f"\n⏳ Adding your idea: {suggestion}")
                story_segment, success = self.process_story_segment(suggestion, is_continuation=True)
                
            elif choice == '4':
                # Request changes to the story
                change_request = input("What changes would you like to make to the story? ")
                print(f"\n⏳ Making changes: {change_request}")
                try:
                    revised_story = self.request_story_changes(change_request)
                    self.story_state.full_story = revised_story
                    story_segment = "Story has been updated with your requested changes!"
                    success = True
                except Exception as e:
                    print(f"❌ Error making changes: {e}")
                    story_segment = "Sorry, I couldn't make those changes. Let's continue with the story."
                    success = False
                    
            elif choice == '5':
                # Change story tone or style
                tone_request = input("How would you like to change the tone or style? (e.g., 'make it more funny', 'make it more magical') ")
                print(f"\n⏳ Changing tone: {tone_request}")
                try:
                    new_tone_story = self.change_story_tone(tone_request)
                    self.story_state.full_story = new_tone_story
                    story_segment = "Story tone has been updated!"
                    success = True
                except Exception as e:
                    print(f"❌ Error changing tone: {e}")
                    story_segment = "Sorry, I couldn't change the tone. Let's continue with the story."
                    success = False
                    
            elif choice == '6':
                # Add a new character
                character_request = input("What new character would you like to add? ")
                print(f"\n⏳ Adding character: {character_request}")
                try:
                    story_with_character = self.add_new_character(character_request)
                    self.story_state.full_story = story_with_character
                    story_segment = "New character has been added to the story!"
                    success = True
                except Exception as e:
                    print(f"❌ Error adding character: {e}")
                    story_segment = "Sorry, I couldn't add that character. Let's continue with the story."
                    success = False
                    
            elif choice == '7':
                # Change the setting
                setting_request = input("What new setting would you like for the story? ")
                print(f"\n⏳ Changing setting: {setting_request}")
                try:
                    adapted_story = self.change_story_setting(setting_request)
                    self.story_state.full_story = adapted_story
                    story_segment = "Story setting has been changed!"
                    success = True
                except Exception as e:
                    print(f"❌ Error changing setting: {e}")
                    story_segment = "Sorry, I couldn't change the setting. Let's continue with the story."
                    success = False
                    
            elif choice == '8':
                # Start a new story
                self.start_new_story()
                continue  # Skip the normal update flow since we've already displayed the new story
                
            elif choice == '9':
                # Exit the system
                print("\n👋 Thank you for using the Interactive Children's Storytelling System!")
                print("🌟 Have a wonderful day filled with stories and adventures!")
                return  # Exit the function entirely
            
            if choice != '2' and choice != '8' and choice != '9':  # Don't update for ending, new story, or exit
                if choice in ['4', '5', '6', '7']:
                    # For change requests, update the full story and show the updated version
                    print("\n" + "="*60)
                    print("📖 STORY UPDATED:")
                    print("="*60)
                    print(self.story_state.full_story)
                else:
                    # For normal story continuation, update and show the new segment
                    self.update_story_state(story_segment)
                    
                    print("\n" + "="*60)
                    print("📖 STORY CONTINUES:")
                    print("="*60)
                    print(story_segment)

def main():
    """Main function matching the original structure"""
    try:
        storytelling_system = StorytellingSystem()
        storytelling_system.run_interactive_story()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye! Thanks for using the storytelling system!")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
        print("Please check your OpenAI API key and try again.")

if __name__ == "__main__":
    main()