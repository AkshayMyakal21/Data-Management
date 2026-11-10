Health Data — UNION & JOIN exercise (Tableau Prep)
Data Management · SRH University of Applied Sciences Heidelberg
All data is fictional and generated for teaching. Join key: Patient_ID

FILES
hospital_branch_north.csv   hospital visits, North branch    (Visit_ID, Patient_ID, Visit_Date, Department)
hospital_branch_south.csv   hospital visits, South branch    (same columns)
hospital_branch_east.csv    hospital visits, East branch     (check the column names!)
patients.csv                patient master data              (Patient_ID, Name, Gender, Birth_Year, City)
medical_records.csv         one record per admission         (Record_ID, Patient_ID, Diagnosis, Admission_Date, Doctor)
billing.csv                 invoices                         (Bill_ID, Patient_ID, Amount_EUR, Insurance, Paid)

TASKS
1. UNION the three branch files into one hospital-visits table.
2. patients.csv        INNER JOIN       medical_records.csv
3. patients.csv        LEFT JOIN        billing.csv
4. medical_records.csv RIGHT JOIN       billing.csv
5. medical_records.csv FULL OUTER JOIN  billing.csv

FOR EVERY STEP, WRITE DOWN
- rows in / rows out
- each null: is it missing data, or "no match"?
- did a join multiply rows? why?
