#!/usr/bin/env python3
"""
Propbot - A prop grading automation tool
Automates the grading of props for projects
"""

import sys
from typing import List, Dict


class PropBot:
    """Main class for prop grading automation"""
    
    def __init__(self):
        """Initialize the PropBot"""
        self.props = []
        self.grades = {}
    
    def add_prop(self, prop_name: str, criteria: Dict[str, float]) -> None:
        """
        Add a prop to be graded
        
        Args:
            prop_name: Name of the prop
            criteria: Dictionary of grading criteria with weights
        """
        self.props.append(prop_name)
        self.grades[prop_name] = criteria
        print(f"Added prop: {prop_name}")
    
    def grade_prop(self, prop_name: str, scores: Dict[str, float]) -> float:
        """
        Grade a prop based on criteria
        
        Args:
            prop_name: Name of the prop to grade
            scores: Dictionary of scores for each criterion
            
        Returns:
            Final weighted grade
        """
        if prop_name not in self.grades:
            print(f"Error: Prop '{prop_name}' not found")
            return 0.0
        
        criteria = self.grades[prop_name]
        total_weight = sum(criteria.values())
        weighted_sum = sum(
            scores.get(criterion, 0) * weight 
            for criterion, weight in criteria.items()
        )
        
        return (weighted_sum / total_weight) if total_weight > 0 else 0.0
    
    def list_props(self) -> None:
        """Display all registered props"""
        if not self.props:
            print("No props registered yet")
            return
        print("Registered props:")
        for prop in self.props:
            print(f"  - {prop}")


def main() -> None:
    """Main entry point"""
    bot = PropBot()
    print("Propbot v1.0 - Prop Grading System")
    print("-" * 40)
    
    # Example usage
    bot.add_prop("Project A", {"completeness": 0.4, "quality": 0.6})
    bot.list_props()
    
    # Grade example
    grade = bot.grade_prop("Project A", {"completeness": 85, "quality": 90})
    print(f"\nFinal Grade: {grade:.2f}")


if __name__ == "__main__":
    main()
