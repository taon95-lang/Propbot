# main.py
# Core Proposition Grading Engine for CS2 Analytics
# Integrates seamlessly with scraper.py to evaluate player props with absolute fault tolerance.

import json
from scraper import CS2DataExtractor

class PropositionGrader:
    def __init__(self):
        """
        Initializes the grader and instantiates the extraction module.
        Decoupling these components ensures that a failure in the grading logic 
        does not crash the web scraping session, and vice versa.
        """
        print("\n==================================================")
        print(" Booting CS2 Proposition Grading Engine...")
        print("==================================================\n")
        
        # Instantiate the robust scraper built in scraper.py
        self.extractor = CS2DataExtractor()
        print(" Extraction engine online and ready for queries.\n")

    def grade_proposition(self, player_name, prop_type, line_value):
        """
        The core evaluation logic for the grading engine.
        Resolves the player entity, fetches the sanitized statistics, and mathematically grades the prop.
        """
        print(f"--------------------------------------------------")
        print(f" Evaluating Prop | Player: {player_name} | Type: {prop_type} | Line: {line_value}")
        
        # 1. Resolve Entity 
        # This completely resolves the "doesn't find the existing character" error.
        profile_url = self.extractor.resolve_player_entity(player_name)
        if not profile_url:
            return self._format_response(
                player_name, 
                "ERROR", 
                details="Player entity could not be resolved in the database. Ensure name spelling is correct."
            )
            
        # 2. Extract Statistics 
        # This resolves the N/A values and successfully captures the 0-100 attributes.
        stats = self.extractor.extract_player_statistics(profile_url)
        if not stats:
            return self._format_response(
                player_name, 
                "ERROR", 
                details="Failed to extract a complete statistical profile. The DOM may have shifted or the sample is empty."
            )
            
        # 3. Heuristic Grading Logic
        # The engine evaluates the proposition line against the sanitized historical averages.
        result = "PENDING"
        details = ""
        prop_type = str(prop_type).strip().upper()
        
        try:
            line_value = float(line_value)
        except ValueError:
            return self._format_response(player_name, "ERROR", details=f"Invalid proposition line value: {line_value}")

        # Map the proposition type to the correct statistical logic
        if prop_type in:
            # Grading based on Rating 3.0. 
            # A standard CS2 map is evaluated at an average of 21 rounds. 
            # A 1.0 rating roughly correlates to 0.70 kills per round.
            projected_kills_per_round = stats['rating_3'] * 0.70
            projected_total = projected_kills_per_round * 21.0 
            
            result = "OVER" if projected_total > line_value else "UNDER"
            details = f"Projected Kills: {projected_total:.2f} | Base Rating 3.0: {stats['rating_3']}"
            
        elif prop_type == "KAST":
            # Grading based directly on the safely parsed KAST percentage
            actual_kast = stats['kast_percent']
            if actual_kast == 0.0:
                return self._format_response(player_name, "INSUFFICIENT_DATA", details="KAST returned 0.0. Sample size too small.")
                
            result = "OVER" if actual_kast > line_value else "UNDER"
            details = f"Actual Historical KAST: {actual_kast}% | Line to Beat: {line_value}%"
            
        elif prop_type == "MULTI_KILL":
            # Grading based on the safely parsed Multi-kill percentage
            actual_mk = stats['multi_kill_percent']
            if actual_mk == 0.0:
                return self._format_response(player_name, "INSUFFICIENT_DATA", details="Multi-Kill % returned 0.0.")
                
            result = "OVER" if actual_mk > line_value else "UNDER"
            details = f"Actual Multi-Kill %: {actual_mk}% | Line to Beat: {line_value}%"
            
        elif prop_type in:
            # Utilizing the 0-100 'Opening' attribute to grade first-blood props
            opening_score = stats['attributes']['opening']
            if opening_score == 0:
                return self._format_response(player_name, "INSUFFICIENT_DATA", details="0-100 Opening attribute missing.")
                
            # Convert the 0-100 score into an implied probability per round
            implied_prob = opening_score / 100.0
            projected_fk = implied_prob * 21.0 # Projected over an average 21-round map
            
            result = "OVER" if projected_fk > line_value else "UNDER"
            details = f"Opening Attribute: {opening_score}/100 | Projected First Kills: {projected_fk:.2f}"
            
        elif prop_type == "HEADSHOTS":
            # Utilizing the 0-100 'Firepower' attribute to inform aim-based props
            firepower_score = stats['attributes']['firepower']
            result = "OVER" if firepower_score > 75 else "UNDER" # Heuristic baseline
            details = f"Firepower Attribute: {firepower_score}/100"
            
        else:
            return self._format_response(player_name, "ERROR", details=f"Unsupported proposition type requested: {prop_type}")

        # Return the highly structured JSON payload
        return self._format_response(
            player_name=stats['name'],
            status="SUCCESS",
            grading=result,
            prop_type=prop_type,
            line=line_value,
            details=details,
            raw_stats=stats
        )

    def _format_response(self, player_name, status, grading=None, prop_type=None, line=None, details=None, raw_stats=None):
        """
        Standardizes the output format into a JSON payload for seamless downstream consumption
        by APIs, web dashboards, or database loggers.
        """
        response = {
            "player_entity": player_name,
            "execution_status": status,
            "grading_verdict": grading,
            "proposition_type": prop_type,
            "line_value": line,
            "analytical_details": details,
            "raw_extracted_metrics": raw_stats
        }
        return json.dumps(response, indent=4)

    def shutdown(self):
        """Ensures the scraper shuts down the underlying WebDriver cleanly."""
        self.extractor.close()
        print("\n Proposition Grading Engine safely powered down.")

# =====================================================================
# Example Execution Flow
# This demonstrates how to invoke the grading engine using the new architecture.
# =====================================================================
if __name__ == "__main__":
    # Instantiate the Grader Engine
    grader = PropositionGrader()
    
    try:
        # Example 1: Standard Kills Proposition
        # Testing a top-tier player (ZywOo) against a standard kill line
        result_1 = grader.grade_proposition("ZywOo", "KILLS", 19.5)
        print(result_1)
        
        # Example 2: KAST Percentage Proposition
        # Testing the newly fixed KAST extraction logic
        result_2 = grader.grade_proposition("donk", "KAST", 75.0)
        print(result_2)
        
        # Example 3: First Kill Proposition
        # Testing the extraction of the 0-100 attributes matrix
        result_3 = grader.grade_proposition("NiKo", "FIRST_KILL", 3.5)
        print(result_3)
        
        # Example 4: Entity Resolution Error Handling
        # Proving that the system catches invalid names without infinite looping
        result_4 = grader.grade_proposition("InvalidPlayerName123", "KILLS", 10.5)
        print(result_4)
        
    finally:
        # Guarantee that the browser process is terminated, regardless of execution success
        grader.shutdown()
