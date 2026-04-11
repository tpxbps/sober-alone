from app.core.llm_factory import create_llm, create_summary_llm

# llm = create_llm(model="doubao-seed-2-0-mini-260215", temperature=0.7)
# response = llm.invoke([{"role": "user", "content": "你是什么模型？"}])
# print(response.content)

summary_llm = create_summary_llm()
response = summary_llm.invoke([{"role": "user", "content": "你是什么模型？"}])
print(response.content)
